"""Online 1v1 combats in a worker host: one side per player, the activation timer,
surrender, and seats surviving recovery."""

import json

import pytest

from app.combat.match import PVP, Match, Seat
from app.shared.clock import FakeClock
from app.shared.errors import GameError
from app.workers.combat_host import CombatHost

HOST, GUEST = 1, 2
COMBAT = "abababab-abab-abab-abab-abababababab"


def _match(timer_s: int | None = 45) -> Match:
    return Match(HOST, PVP, (Seat(0, HOST, "ada"), Seat(1, GUEST, "bo")), timer_s)


def _host(ruleset, store, clock: FakeClock, pushes: list) -> CombatHost:
    return CombatHost(
        ruleset,
        store,
        slot=0,
        publish=lambda cid, update: pushes.append(json.loads(update)),
        clock=clock,
        idle_timeout_s=24 * 3600,
    )


def _active_side(view: dict) -> int:
    uid = view["active"]["uid"]
    return next(u["side"] for u in view["units"] if u["uid"] == uid)


def _holder(side: int) -> int:
    return HOST if side == 0 else GUEST


async def test_each_player_acts_only_for_their_side(
    ruleset, store, demo_setup_json
) -> None:
    clock, pushes = FakeClock(), []
    host = _host(ruleset, store, clock, pushes)
    snapshot = await host.create(COMBAT, _match(), demo_setup_json)
    assert snapshot["board"]["players"] == [
        {"side": 0, "user_id": HOST, "name": "ada"},
        {"side": 1, "user_id": GUEST, "name": "bo"},
    ]
    side = _active_side(snapshot["view"])
    with pytest.raises(GameError, match="combat.not_your_turn"):
        await host.intent(COMBAT, _holder(1 - side), {"type": "skip"})
    await host.intent(COMBAT, _holder(side), {"type": "skip"})
    with pytest.raises(GameError, match="combat.not_a_participant"):
        await host.subscribe(COMBAT, 3, None)


async def test_the_timer_skips_for_a_slow_player(
    ruleset, store, demo_setup_json
) -> None:
    clock, pushes = FakeClock(), []
    host = _host(ruleset, store, clock, pushes)
    snapshot = await host.create(COMBAT, _match(45), demo_setup_json)
    assert snapshot["deadline_ms"] == int((clock.now() + 45) * 1000)

    clock.advance(44)
    await host.tick()
    assert pushes == []  # not yet
    clock.advance(2)
    await host.tick()
    [update] = pushes
    assert update["events"] and update["deadline_ms"] == int((clock.now() + 45) * 1000)
    await host.drain()
    [stored] = await store.load_active(0)
    assert [a["type"] for a in stored.actions] == ["skip"]  # recorded, replayable


async def test_a_player_action_keeps_the_activation_deadline(
    ruleset, store, demo_setup_json
) -> None:
    """The timer is per activation: re-armed only when a new activation starts."""
    clock, pushes = FakeClock(), []
    host = _host(ruleset, store, clock, pushes)
    snapshot = await host.create(COMBAT, _match(45), demo_setup_json)
    instance = host.instances[COMBAT]
    before = instance.activations
    clock.advance(10)
    await host.intent(COMBAT, _holder(_active_side(snapshot["view"])), {"type": "skip"})
    expected = (
        snapshot["deadline_ms"]
        if instance.activations == before
        else int((clock.now() + 45) * 1000)
    )
    assert pushes[-1]["deadline_ms"] == expected


async def test_untimed_combats_have_no_deadline(
    ruleset, store, demo_setup_json
) -> None:
    clock, pushes = FakeClock(), []
    host = _host(ruleset, store, clock, pushes)
    snapshot = await host.create(COMBAT, _match(None), demo_setup_json)
    assert snapshot["deadline_ms"] is None
    clock.advance(10_000)
    await host.tick()
    assert pushes == []


async def test_surrender_gives_the_opponent_the_win(
    ruleset, store, demo_setup_json
) -> None:
    clock, pushes = FakeClock(), []
    host = _host(ruleset, store, clock, pushes)
    await host.create(COMBAT, _match(), demo_setup_json)
    await host.concede(COMBAT, GUEST)
    assert pushes[-1]["view"]["outcome"] == {
        "winners": [0],
        "draw": False,
        "reason": "concede",
    }
    assert pushes[-1]["deadline_ms"] is None
    [summary] = await store.list_for_user(GUEST)
    assert summary.status == "finished"
    with pytest.raises(GameError, match="combat.finished"):
        await host.concede(COMBAT, HOST)


async def test_hotseat_owners_cant_concede(ruleset, store, demo_setup_json) -> None:
    host = _host(ruleset, store, FakeClock(), [])
    await host.create(COMBAT, Match.hotseat(HOST, (0, 1)), demo_setup_json)
    with pytest.raises(GameError, match="combat.not_a_participant"):
        await host.concede(COMBAT, HOST)


async def test_seats_and_timer_survive_recovery(
    ruleset, store, demo_setup_json
) -> None:
    clock = FakeClock()
    await _host(ruleset, store, clock, []).create(COMBAT, _match(60), demo_setup_json)
    [stored] = await store.load_active(0)
    assert stored.match == _match(60)
    assert await store.participants(COMBAT) == {HOST, GUEST}
    assert [s.combat_id for s in await store.list_for_user(GUEST)] == [COMBAT]
    assert await store.active_for_user(GUEST, PVP) is not None
    assert await store.active_for_user(GUEST, "hotseat") is None

    restarted = _host(ruleset, store, clock, [])  # a fresh, full timer after recovery
    reply = await restarted.subscribe(COMBAT, GUEST, None)
    assert reply["snapshot"]["board"]["players"][1]["user_id"] == GUEST
    assert reply["snapshot"]["deadline_ms"] == int((clock.now() + 60) * 1000)
