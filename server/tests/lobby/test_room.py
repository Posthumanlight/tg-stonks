"""The room domain and the in-memory store (docs/lobby-rooms.md). Pure: no I/O."""

import pytest

from app.combat.ground.deployment import Army, ArmyUnit
from app.lobby.room import (
    CLOSED,
    CLOSED_EXPIRED,
    CLOSED_HOST_GONE,
    CLOSED_HOST_LEFT,
    FULL,
    OPEN,
    STARTING,
    Member,
    Room,
    RoomSettings,
)
from app.lobby.store import MemoryRoomStore, new_code, normalize_code
from app.shared.errors import GameError

HOST, GUEST, OTHER = 1, 2, 3
ARMY = Army("concord", (ArmyUnit("warden", (0, 0)),))
LIMITS = {"idle_ttl_s": 1800, "guest_grace_s": 30, "host_grace_s": 60}


def _room(
    room_id: str = "r1",
    *,
    name: str = "Friday fight",
    private: bool = False,
    points: int = 1000,
    created_at: float = 0.0,
) -> Room:
    return Room(
        room_id,
        f"CODE{room_id[-2:]:>02}",
        RoomSettings(name, private, points, 45),
        Member(HOST, "ada", 0),
        created_at=created_at,
        touched_at=0.0,
    )


def _reason(call) -> str:  # noqa: ANN001
    with pytest.raises(GameError) as caught:
        call()
    return caught.value.reason_key


def test_join_fills_the_room_once() -> None:
    room = _room()
    guest = room.join(GUEST, "bo", now=1)
    assert (guest.side, room.status) == (1, FULL)
    assert room.join(GUEST, "bo", now=2) is guest  # a reconnect: no-op
    assert _reason(lambda: room.join(OTHER, "cy", now=3)) == "room.full"


def test_leaving() -> None:
    room = _room()
    room.join(GUEST, "bo", now=1)
    room.ready(HOST, ARMY, now=2)
    assert room.leave(GUEST, now=3) is None
    assert (room.guest, room.status, room.host.ready) == (None, OPEN, True)
    assert _reason(lambda: room.leave(GUEST, now=4)) == "room.not_member"
    assert room.leave(HOST, now=5) == CLOSED_HOST_LEFT
    assert room.status == CLOSED
    assert _reason(lambda: room.join(OTHER, "cy", now=6)) == "room.not_found"


def test_only_the_host_kicks_and_the_kicked_cant_return() -> None:
    room = _room()
    room.join(GUEST, "bo", now=1)
    assert _reason(lambda: room.kick(GUEST, now=2)) == "room.not_host"
    assert room.kick(HOST, now=2) == GUEST
    assert room.status == OPEN
    assert _reason(lambda: room.join(GUEST, "bo", now=3)) == "room.kicked"
    assert _reason(lambda: room.kick(HOST, now=3)) == "room.no_guest"
    room.join(OTHER, "cy", now=4)  # someone else may


def test_ready_and_start_lock() -> None:
    room = _room()
    room.ready(HOST, ARMY, now=1)  # before the guest arrives is fine
    room.join(GUEST, "bo", now=2)
    assert not room.both_ready
    assert _reason(room.begin_start) == "room.not_ready"
    room.ready(GUEST, ARMY, now=3)
    assert room.begin_start() == (ARMY, ARMY)
    assert room.status == STARTING
    for call in (
        lambda: room.unready(HOST, now=4),
        lambda: room.leave(GUEST, now=4),
        lambda: room.kick(HOST, now=4),
        room.begin_start,
    ):
        assert _reason(call) in ("room.locked", "room.not_ready")
    room.abort_start(now=5)
    assert room.status == FULL and not room.host.ready and not room.guest.ready


def test_grace_periods_and_idle_expiry() -> None:
    room = _room()
    room.join(GUEST, "bo", now=0)
    room.disconnected(GUEST, now=10)
    assert room.expire(40, **LIMITS).dropped_guest is None  # 30 s exactly: still in
    assert room.expire(41, **LIMITS).dropped_guest == GUEST
    assert room.status == OPEN

    room.disconnected(HOST, now=100)
    room.connected(HOST)  # back in time
    assert room.expire(1000, **LIMITS).closed is None
    room.disconnected(HOST, now=1000)
    assert room.expire(1061, **LIMITS).closed == CLOSED_HOST_GONE

    idle = _room("r2")
    assert idle.expire(1800, **LIMITS).closed is None
    assert idle.expire(1801, **LIMITS).closed == CLOSED_EXPIRED


def test_codes() -> None:
    code = new_code()
    assert len(code) == 6 and normalize_code(code.lower()) == code
    assert normalize_code(" ab-c o1l ") == "ABC011"


def test_store_indexes_and_search() -> None:
    store = MemoryRoomStore()
    old, new, private = (
        _room("r1", name="Old Friday", created_at=1),
        _room("r2", name="new friday", created_at=2, points=500),
        _room("r3", name="Friday secret", created_at=3, private=True),
    )
    for room in (old, new, private):
        store.add(room)
        store.bind(HOST + int(room.room_id[-1]) * 10, room.room_id)
    assert store.by_code(new.code) is new and store.code_taken(old.code)
    assert [r.room_id for r in store.search("FRIDAY", None, 50)] == ["r2", "r1"]
    assert [r.room_id for r in store.search("", 500, 50)] == ["r2"]
    assert store.search("", None, 1) == [new]
    old.join(GUEST, "bo", now=1)  # full rooms aren't listed
    assert [r.room_id for r in store.search("", None, 50)] == ["r2"]

    store.bind(GUEST, "r1")
    assert store.of_user(GUEST) is old
    store.remove("r1")
    assert store.of_user(GUEST) is None and store.by_code(old.code) is None
