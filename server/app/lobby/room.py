"""A lobby room (docs/lobby-rooms.md): pure domain, no I/O, no clock of its own.

The host creates it; one guest joins (from search, or by code). Each player builds and
deploys their side, then readies; when both are ready the service starts the battle.

    open ──join──► full ──both ready──► starting ──► closed (battle started)
     ▲               │
     └─guest leaves,─┘        any ──host leaves / expires──► closed
       kicked or gone

Methods raise `GameError` with `room.*` reasons; times are passed in (monotonic s).
"""

from dataclasses import dataclass, field

from app.combat.ground.deployment import Army
from app.shared.errors import GameError

OPEN, FULL, STARTING, CLOSED = "open", "full", "starting", "closed"
HOST_SIDE, GUEST_SIDE = 0, 1

# Why a room closed (sent to its members as `room.closed {reason}`).
CLOSED_HOST_LEFT = "room.closed.host_left"
CLOSED_HOST_GONE = "room.closed.host_gone"
CLOSED_EXPIRED = "room.closed.expired"
CLOSED_KICKED = "room.closed.kicked"  # to the kicked guest only


@dataclass(frozen=True, slots=True)
class RoomSettings:
    name: str
    private: bool  # hidden from search; joinable by code only
    points_limit: int  # 0 = unlimited
    timer_s: int  # seconds per activation; 0 = unlimited


@dataclass(slots=True)
class Member:
    user_id: int
    name: str
    side: int
    army: Army | None = (
        None  # set by Ready (validated by the service); None = not ready
    )
    gone_since: float | None = None  # monotonic time of the disconnect; None = here

    @property
    def ready(self) -> bool:
        return self.army is not None


@dataclass(frozen=True, slots=True)
class Expiry:
    """What `Room.expire` decided: a guest dropped, or the room closed."""

    dropped_guest: int | None = None
    closed: str | None = None  # a CLOSED_* reason


@dataclass(slots=True)
class Room:
    room_id: str
    code: str
    settings: RoomSettings
    host: Member
    created_at: float  # wall clock (sorting, display)
    touched_at: float  # monotonic (idle expiry)
    guest: Member | None = None
    status: str = OPEN
    kicked: set[int] = field(default_factory=set)

    @property
    def members(self) -> tuple[Member, ...]:
        return (self.host,) if self.guest is None else (self.host, self.guest)

    def member(self, user_id: int) -> Member:
        for member in self.members:
            if member.user_id == user_id:
                return member
        raise GameError("room.not_member", 403)

    def is_member(self, user_id: int) -> bool:
        return any(m.user_id == user_id for m in self.members)

    @property
    def both_ready(self) -> bool:
        return self.guest is not None and self.host.ready and self.guest.ready

    # --- membership --------------------------------------------------------------------

    def join(self, user_id: int, name: str, now: float) -> Member:
        """Take the guest seat. Joining a room you're in is a no-op (a reconnect)."""
        if self.is_member(user_id):
            return self.member(user_id)
        if user_id in self.kicked:
            raise GameError("room.kicked", 403)
        if self.status == CLOSED:
            raise GameError("room.not_found", 404)
        if self.status != OPEN:
            raise GameError("room.full", 409)
        self.guest = Member(user_id, name, GUEST_SIDE)
        self.status = FULL
        self.touched_at = now
        return self.guest

    def leave(self, user_id: int, now: float) -> str | None:
        """A member leaves. Returns the close reason when the room closes (the host
        left), else None (the guest left; the room is open again)."""
        self._unlocked()
        member = self.member(user_id)
        self.touched_at = now
        if member is self.host:
            self.status = CLOSED
            return CLOSED_HOST_LEFT
        self._drop_guest()
        return None

    def kick(self, by_user_id: int, now: float) -> int:
        """The host removes the guest, who can't rejoin. Returns the guest's id."""
        self._unlocked()
        if self.member(by_user_id) is not self.host:
            raise GameError("room.not_host", 403)
        if self.guest is None:
            raise GameError("room.no_guest", 409)
        guest = self.guest.user_id
        self.kicked.add(guest)
        self._drop_guest()
        self.touched_at = now
        return guest

    # --- readiness ---------------------------------------------------------------------

    def ready(self, user_id: int, army: Army, now: float) -> None:
        """Lock in a (validated) army. Allowed before the guest arrives, too."""
        self._unlocked()
        self.member(user_id).army = army
        self.touched_at = now

    def unready(self, user_id: int, now: float) -> None:
        self._unlocked()
        self.member(user_id).army = None
        self.touched_at = now

    def begin_start(self) -> tuple[Army, Army]:
        """Both are ready: lock the room (no leave/ready/kick) and hand over the
        armies in side order. Set before any await, so a battle starts only once."""
        if not self.both_ready or self.status != FULL:
            raise GameError("room.not_ready", 409)
        assert self.guest is not None and self.host.army and self.guest.army
        self.status = STARTING
        return self.host.army, self.guest.army

    def abort_start(self, now: float) -> None:
        """Starting failed (e.g. a player already has a battle): back to full, and
        everyone unready so the problem can be fixed."""
        self.status = FULL
        for member in self.members:
            member.army = None
        self.touched_at = now

    # --- presence and expiry -----------------------------------------------------------

    def disconnected(self, user_id: int, now: float) -> None:
        if self.is_member(user_id):
            self.member(user_id).gone_since = now

    def connected(self, user_id: int) -> None:
        if self.is_member(user_id):
            self.member(user_id).gone_since = None

    def expire(
        self,
        now: float,
        *,
        idle_ttl_s: float,
        guest_grace_s: float,
        host_grace_s: float,
    ) -> Expiry:
        """Apply the grace periods and the idle limit. A starting room is left alone
        (the service is creating its battle)."""
        if self.status in (STARTING, CLOSED):
            return Expiry()
        if _gone_for(self.host, now) > host_grace_s:
            self.status = CLOSED
            return Expiry(closed=CLOSED_HOST_GONE)
        if now - self.touched_at > idle_ttl_s:
            self.status = CLOSED
            return Expiry(closed=CLOSED_EXPIRED)
        if self.guest is not None and _gone_for(self.guest, now) > guest_grace_s:
            guest = self.guest.user_id
            self._drop_guest()
            self.touched_at = now
            return Expiry(dropped_guest=guest)
        return Expiry()

    # --- internals ---------------------------------------------------------------------

    def _unlocked(self) -> None:
        if self.status == STARTING:
            raise GameError("room.locked", 409)
        if self.status == CLOSED:
            raise GameError("room.not_found", 404)

    def _drop_guest(self) -> None:
        self.guest = None
        self.status = OPEN


def _gone_for(member: Member, now: float) -> float:
    return 0.0 if member.gone_since is None else now - member.gone_since
