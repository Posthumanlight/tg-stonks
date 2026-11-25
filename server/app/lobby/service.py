"""The lobby manager (docs/lobby-rooms.md): create, search and join rooms, ready up, and
start the online battle when both players are ready.

Everything runs on the gateway's single event loop. A room is changed only between
awaits, and `Room.begin_start` locks it before the one await that creates the battle,
so no lock is needed.
"""

import uuid
from collections.abc import Awaitable, Callable
from math import ceil
from typing import Any

from app.combat.ground.deployment import (
    BattleMap,
    army_points,
    deploy,
    deploy_side,
)
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.serialize import setup_to_json
from app.combat.ground.setup import SetupError
from app.combat.match import PVP, Match, Seat
from app.lobby.hub import RoomHub, RoomSubscriber
from app.lobby.room import (
    CLOSED_KICKED,
    HOST_SIDE,
    Member,
    Room,
    RoomSettings,
)
from app.lobby.store import RoomStore, new_code, normalize_code
from app.protocol.builder import SideSetup, army_from_side
from app.protocol.rooms import CreateRoomRequest, room_view
from app.services.combat_router import CombatRouter
from app.shared.clock import Clock
from app.shared.errors import GameError, from_setup_error
from app.shared.ratelimit import KeyedRateLimiter

UserName = Callable[[int], Awaitable[str]]

CLOSED_GUEST_GONE = "room.closed.gone"  # to a guest whose grace period ran out
JOINS_PER_MINUTE = 20  # per user: codes are short, so guessing must be slow
SWEEP_INTERVAL_S = 5.0


class RoomService:
    def __init__(
        self,
        *,
        store: RoomStore,
        ruleset: CombatRuleset,
        battle_map: BattleMap,
        combats: CombatRouter,
        user_name: UserName,
        clock: Clock,
        join_limiter: KeyedRateLimiter | None = None,
    ) -> None:
        self._store = store
        self._ruleset = ruleset
        self._map = battle_map  # with the deployment zones
        self._combats = combats
        self._user_name = user_name
        self._clock = clock
        self._joins = join_limiter or KeyedRateLimiter.per_minute(
            JOINS_PER_MINUTE, clock
        )
        self._pvp = ruleset.rules.pvp
        self.hub = RoomHub(self._render)

    # --- finding rooms -----------------------------------------------------------------

    def search(self, query: str, points_limit: int | None, limit: int) -> list[Room]:
        return self._store.search(query, points_limit, limit)

    def mine(self, user_id: int) -> Room | None:
        return self._store.of_user(user_id)

    # --- membership --------------------------------------------------------------------

    async def create(self, user_id: int, request: CreateRoomRequest) -> Room:
        if request.points_limit not in self._pvp.points_presets:
            raise GameError("room.bad_points", 400)
        if request.timer_s not in self._pvp.timer_presets:
            raise GameError("room.bad_timer", 400)
        await self._require_free(user_id)
        name = await self._user_name(user_id)
        await self._require_free(user_id)  # re-checked: the name lookup awaited
        room = Room(
            str(uuid.uuid4()),
            self._unique_code(),
            RoomSettings(
                request.name, request.private, request.points_limit, request.timer_s
            ),
            Member(user_id, name, HOST_SIDE),
            created_at=self._clock.now(),
            touched_at=self._clock.monotonic(),
        )
        self._store.add(room)
        self._store.bind(user_id, room.room_id)
        return room

    async def join(
        self, user_id: int, *, room_id: str | None = None, code: str | None = None
    ) -> Room:
        """Join from search (`room_id`, public rooms) or with a code (any room)."""
        wait = self._joins.hit(user_id)
        if wait is not None:
            raise GameError(
                "room.rate_limited", 429, headers={"Retry-After": str(ceil(wait))}
            )
        room = self._find(room_id, code)
        if room.is_member(user_id):
            return room  # already in: a reconnect
        await self._require_free(user_id)
        name = await self._user_name(user_id)
        room = self._find(room_id, code)  # it may have changed during the await
        await self._require_free(user_id)
        room.join(user_id, name, self._clock.monotonic())
        self._store.bind(user_id, room.room_id)
        self.hub.publish(room)
        return room

    def leave(self, user_id: int, room_id: str) -> None:
        room = self._room(room_id)
        closed = room.leave(user_id, self._clock.monotonic())
        self._store.unbind(user_id)
        if closed is not None:
            self._close(room, closed)
        else:
            self.hub.closed(room_id, "room.closed.left", only=frozenset({user_id}))
            self.hub.publish(room)

    def kick(self, user_id: int, room_id: str) -> None:
        room = self._room(room_id)
        guest = room.kick(user_id, self._clock.monotonic())
        self._store.unbind(guest)
        self.hub.closed(room_id, CLOSED_KICKED, only=frozenset({guest}))
        self.hub.publish(room)

    # --- readiness and the battle ------------------------------------------------------

    async def ready(self, user_id: int, room_id: str, side: SideSetup) -> str | None:
        """Lock in the player's army (validated alone, in their zone and the room's
        points limit). Returns the battle's id when this made both players ready."""
        room = self._room(room_id)
        member = room.member(user_id)
        army = army_from_side(side)
        try:
            deploy_side(
                self._ruleset,
                self._map,
                member.side,
                army,
                points_limit=room.settings.points_limit or None,
            )
        except SetupError as exc:
            raise from_setup_error(exc) from exc
        room.ready(user_id, army, self._clock.monotonic())
        if room.both_ready:
            return await self._start(room)
        self.hub.publish(room)
        return None

    def unready(self, user_id: int, room_id: str) -> None:
        room = self._room(room_id)
        room.unready(user_id, self._clock.monotonic())
        self.hub.publish(room)

    async def _start(self, room: Room) -> str:
        armies = room.begin_start()  # locked from here: leave/ready/kick are refused
        self.hub.publish(room)
        try:
            setup = deploy(
                self._ruleset,
                self._map,
                armies,
                points_limit=room.settings.points_limit or None,
            )
            match = Match(
                room.host.user_id,
                PVP,
                tuple(Seat(m.side, m.user_id, m.name) for m in room.members),
                room.settings.timer_s or None,
            )
            combat_id = await self._combats.start(match, setup_to_json(setup))
        except (SetupError, GameError) as exc:
            room.abort_start(self._clock.monotonic())
            self.hub.publish(room)
            if isinstance(exc, SetupError):
                raise from_setup_error(exc) from exc
            raise
        self._store.remove(room.room_id)
        self.hub.started(room.room_id, combat_id)
        return combat_id

    # --- presence (WebSocket) ----------------------------------------------------------

    def subscribe(self, subscriber: RoomSubscriber, room_id: str) -> None:
        room = self._room(room_id)
        room.member(subscriber.user_id)  # members only
        self.hub.add(room_id, subscriber)
        room.connected(subscriber.user_id)
        self.hub.publish(room)

    def unsubscribe(self, subscriber: RoomSubscriber, room_id: str) -> None:
        if not self.hub.remove(room_id, subscriber):
            return
        room = self._store.get(room_id)
        if room is not None:
            room.disconnected(subscriber.user_id, self._clock.monotonic())
            self.hub.publish(room)

    def drop(self, subscriber: RoomSubscriber) -> None:
        """A socket closed: its presence ends in every room it watched."""
        for room_id in self.hub.rooms_of(subscriber):
            self.unsubscribe(subscriber, room_id)

    async def sweep(self) -> None:
        """Grace periods and idle expiry (one periodic task for all rooms)."""
        now = self._clock.monotonic()
        for room in self._store.all():
            expiry = room.expire(
                now,
                idle_ttl_s=self._pvp.room_idle_ttl_s,
                guest_grace_s=self._pvp.guest_grace_s,
                host_grace_s=self._pvp.host_grace_s,
            )
            if expiry.closed is not None:
                self._close(room, expiry.closed)
            elif expiry.dropped_guest is not None:
                self._store.unbind(expiry.dropped_guest)
                self.hub.closed(
                    room.room_id,
                    CLOSED_GUEST_GONE,
                    only=frozenset({expiry.dropped_guest}),
                )
                self.hub.publish(room)

    # --- internals ---------------------------------------------------------------------

    def _render(self, room: Room, viewer: int) -> dict[str, Any]:
        view = room_view(room, viewer, lambda a: army_points(self._ruleset, a))
        return view.model_dump(mode="json")

    def view(self, room_id: str, viewer: int) -> dict[str, Any]:
        return self._render(self._room(room_id), viewer)

    def _room(self, room_id: str) -> Room:
        room = self._store.get(room_id)
        if room is None:
            raise GameError("room.not_found", 404)
        return room

    def _find(self, room_id: str | None, code: str | None) -> Room:
        if code is not None:
            room = self._store.by_code(normalize_code(code))
        else:
            room = self._store.get(room_id or "")
            if room is not None and room.settings.private:
                room = None  # private rooms are joined by code only
        if room is None:
            raise GameError("room.not_found", 404)
        return room

    async def _require_free(self, user_id: int) -> None:
        """One room at a time, and none while an online battle is running."""
        if self._store.of_user(user_id) is not None:
            raise GameError("room.already_in_room", 409)
        if await self._combats.has_active(user_id, PVP):
            raise GameError("combat.already_active", 409)

    def _unique_code(self) -> str:
        while True:
            code = new_code()
            if not self._store.code_taken(code):
                return code

    def _close(self, room: Room, reason: str) -> None:
        self._store.remove(room.room_id)
        self.hub.closed(room.room_id, reason)
