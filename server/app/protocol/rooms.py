"""Lobby room bodies (docs/protocol.md "Lobby rooms") and the per-viewer room view.

A viewer sees their own locked army in full, but only the opponent's faction, points
and unit count: deployment stays hidden until the battle starts.
"""

from collections.abc import Callable

from pydantic import Field, field_validator

from app.combat.ground.deployment import Army
from app.lobby.room import Member, Room
from app.protocol.base import ProtocolModel
from app.protocol.builder import SideSetup, request_side

ROOM_NAME_MAX = 40
ROOM_LIST_MAX = 50

PointsOf = Callable[[Army], int]  # prices an army (content)


class CreateRoomRequest(ProtocolModel):
    name: str = Field(min_length=1, max_length=ROOM_NAME_MAX)
    private: bool = False
    points_limit: int = Field(ge=0)  # one of the content presets; 0 = unlimited
    timer_s: int = Field(ge=0)  # one of the content presets; 0 = unlimited

    @field_validator("name")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("empty name")
        return value


class JoinByCodeRequest(ProtocolModel):
    code: str = Field(min_length=1, max_length=16)


class RoomJoined(ProtocolModel):
    room_id: str
    code: str


class MyRoom(ProtocolModel):
    room: RoomJoined | None  # null: not in a room


class RoomReady(ProtocolModel):
    combat_id: str | None  # set when this made both players ready: the battle began


class RoomCard(ProtocolModel):
    """One open public room in search results."""

    room_id: str
    name: str
    host_name: str
    points_limit: int
    timer_s: int


class RoomList(ProtocolModel):
    rooms: list[RoomCard]


class RoomPlayer(ProtocolModel):
    user_id: int
    name: str
    side: int
    ready: bool
    connected: bool
    # Shown once the player is ready (their army is locked); never the positions.
    faction: str | None
    points: int | None
    unit_count: int | None


class RoomView(ProtocolModel):
    room_id: str
    code: str
    name: str
    private: bool
    points_limit: int
    timer_s: int
    status: str  # open | full | starting
    host_user_id: int
    your_side: int
    players: list[RoomPlayer]
    your_army: SideSetup | None  # what you readied with (restores the builder)


class RoomStarted(ProtocolModel):
    room_id: str
    combat_id: str


class RoomClosed(ProtocolModel):
    room_id: str
    reason: str  # room.closed.* (host_left, host_gone, expired, kicked, gone, left)


# --- converters (pure) -----------------------------------------------------------------


def room_card(room: Room) -> RoomCard:
    settings = room.settings
    return RoomCard(
        room_id=room.room_id,
        name=settings.name,
        host_name=room.host.name,
        points_limit=settings.points_limit,
        timer_s=settings.timer_s,
    )


def room_view(room: Room, viewer: int, points_of: PointsOf) -> RoomView:
    """`viewer` must be a member. `points_of` prices an army (content)."""
    you = room.member(viewer)
    settings = room.settings
    return RoomView(
        room_id=room.room_id,
        code=room.code,
        name=settings.name,
        private=settings.private,
        points_limit=settings.points_limit,
        timer_s=settings.timer_s,
        status=room.status,
        host_user_id=room.host.user_id,
        your_side=you.side,
        players=[_player(m, points_of) for m in room.members],
        your_army=request_side(you.army) if you.army is not None else None,
    )


def _player(member: Member, points_of: PointsOf) -> RoomPlayer:
    army = member.army
    return RoomPlayer(
        user_id=member.user_id,
        name=member.name,
        side=member.side,
        ready=army is not None,
        connected=member.gone_since is None,
        faction=army.faction if army is not None else None,
        points=points_of(army) if army is not None else None,
        unit_count=len(army.units) if army is not None else None,
    )
