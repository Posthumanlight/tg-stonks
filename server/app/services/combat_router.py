"""Gateway side of combats: placement on workers, routing, and fan-out to subscribers."""

import uuid
from typing import Any, Protocol

from app.persistence.combat_repo import ACTIVE, CombatStore
from app.services.combat_backend import CombatBackend
from app.shared.errors import GameError

HOTSEAT = "hotseat"


class Subscriber(Protocol):
    """What the router needs from a client connection (implemented by the WS layer)."""

    def push_combat_update(self, combat_id: str, update_json: str) -> None:
        """`update_json` is a serialized CombatUpdate, forwarded as is."""


class CombatRouter:
    def __init__(self, backend: CombatBackend, store: CombatStore) -> None:
        self._backend = backend
        self._store = store
        self._slots: dict[str, int] = {}
        self._subscribers: dict[str, set[Subscriber]] = {}
        self._creating: set[int] = set()  # users with a create in flight
        backend.on_push(self._fan_out)

    # --- combats -----------------------------------------------------------------------

    async def start_hotseat(
        self, user_id: int, setup: dict[str, Any], *, resume_active: bool
    ) -> str:
        """Start a hotseat combat from a validated setup (JSON). One active hotseat per
        user: with one already running, return it (`resume_active`, the quick battle)
        or refuse with `combat.already_active` (a custom battle mustn't be dropped)."""
        if user_id in self._creating:  # a double tap: the first request wins
            raise GameError("combat.already_active", 409)
        self._creating.add(user_id)
        try:
            existing = await self._store.active_for_owner(user_id, HOTSEAT)
            if existing is not None:
                if not resume_active:
                    raise GameError("combat.already_active", 409)
                self._slots[existing.combat_id] = existing.worker_slot
                return existing.combat_id
            loads = self._backend.loads()
            slot = min(range(len(loads)), key=lambda s: (loads[s], s))
            combat_id = str(uuid.uuid4())
            await self._backend.create(slot, combat_id, user_id, HOTSEAT, setup)
            self._slots[combat_id] = slot
            return combat_id
        finally:
            self._creating.discard(user_id)

    async def abandon(self, user_id: int, combat_id: str) -> None:
        """The owner gives up an active combat; it ends without an outcome."""
        summary = await self._store.summary(combat_id)
        if summary is None:
            raise GameError("combat.not_found", 404)
        if summary.owner_user_id != user_id:
            raise GameError("combat.not_a_participant", 403)
        if summary.status != ACTIVE:
            raise GameError("combat.finished", 409)
        await self._backend.close(summary.worker_slot, combat_id, "player")
        self._slots.pop(combat_id, None)

    async def intent(
        self, user_id: int, combat_id: str, intent: dict[str, Any]
    ) -> None:
        await self._backend.intent(
            await self._slot(combat_id), combat_id, user_id, intent
        )

    async def subscribe(
        self, subscriber: Subscriber, user_id: int, combat_id: str, last_seq: int | None
    ) -> dict[str, Any]:
        """Returns `{kind: "events" | "snapshot", ...}`; later updates are pushed."""
        payload = await self._backend.subscribe(
            await self._slot(combat_id), combat_id, user_id, last_seq
        )
        self._subscribers.setdefault(combat_id, set()).add(subscriber)
        return payload

    def unsubscribe(self, subscriber: Subscriber, combat_id: str) -> None:
        subscribers = self._subscribers.get(combat_id)
        if subscribers is not None:
            subscribers.discard(subscriber)
            if not subscribers:
                del self._subscribers[combat_id]

    def drop(self, subscriber: Subscriber) -> None:
        """A connection closed: forget it everywhere."""
        for combat_id in list(self._subscribers):
            self.unsubscribe(subscriber, combat_id)

    # --- internals ---------------------------------------------------------------------

    async def _slot(self, combat_id: str) -> int:
        slot = self._slots.get(combat_id)
        if slot is None:
            try:
                uuid.UUID(combat_id)
            except ValueError as exc:
                raise GameError("combat.not_found", 404) from exc
            slot = await self._store.slot_of(combat_id)
            if slot is None:
                raise GameError("combat.not_found", 404)
            self._slots[combat_id] = slot
        return slot

    def _fan_out(self, combat_id: str, update_json: str) -> None:
        for subscriber in list(self._subscribers.get(combat_id, ())):
            subscriber.push_combat_update(combat_id, update_json)
