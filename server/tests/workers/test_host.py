"""CombatHost: persistence (immediate + write-behind), lazy recovery by replay, sweeping."""

import asyncio

import pytest

from app.combat.match import Match
from app.combat.ground.events import log_hash
from app.persistence.write_behind import WriteBehindBuffer
from app.shared.clock import FakeClock
from app.shared.errors import GameError
from app.workers.combat_host import CombatHost

OWNER = 1
HOTSEAT_MATCH = Match.hotseat(OWNER, (0, 1))


def _host(ruleset, store, clock=None, pushes=None, slot=0) -> CombatHost:
    return CombatHost(
        ruleset,
        store,
        slot=slot,
        publish=lambda cid, update: (pushes if pushes is not None else []).append(
            (cid, update)
        ),
        clock=clock or FakeClock(),
        idle_timeout_s=3600,
    )


async def test_create_persists_and_snapshots(ruleset, store, demo_setup_json) -> None:
    host = _host(ruleset, store)
    snapshot = await host.create(
        "11111111-1111-1111-1111-111111111111", HOTSEAT_MATCH, demo_setup_json
    )
    assert snapshot["board"]["width"] == 24 and snapshot["view"]["round"] == 1
    assert snapshot["legal"] is not None
    [stored] = await store.load_active(0)
    assert stored.match.owner_user_id == OWNER and stored.actions == ()
    assert stored.content_hash == ruleset.content_hash


async def test_bad_setup_is_refused(ruleset, store) -> None:
    with pytest.raises(GameError, match="combat.bad_setup"):
        await _host(ruleset, store).create(
            "22222222-2222-2222-2222-222222222222", HOTSEAT_MATCH, {"board": {}}
        )


async def test_intents_push_and_write_behind(ruleset, store, demo_setup_json) -> None:
    pushes: list = []
    host = _host(ruleset, store, pushes=pushes)
    combat_id = "33333333-3333-3333-3333-333333333333"
    await host.create(combat_id, HOTSEAT_MATCH, demo_setup_json)
    for _ in range(3):
        await host.intent(combat_id, OWNER, {"type": "wait" if _ == 0 else "skip"})
    assert len(pushes) == 3 and all(cid == combat_id for cid, _ in pushes)
    assert len(host.writes) == 3
    assert (await store.load_active(0))[0].actions == ()  # not flushed yet
    await host.writes.flush()
    assert [a["type"] for a in (await store.load_active(0))[0].actions] == [
        "wait",
        "skip",
        "skip",
    ]


async def test_refused_intents_are_not_recorded(
    ruleset, store, demo_setup_json
) -> None:
    host = _host(ruleset, store)
    combat_id = "44444444-4444-4444-4444-444444444444"
    await host.create(combat_id, HOTSEAT_MATCH, demo_setup_json)
    with pytest.raises(GameError, match="combat.not_your_turn"):
        await host.intent(combat_id, 2, {"type": "skip"})
    with pytest.raises(GameError, match="request.invalid"):
        await host.intent(combat_id, OWNER, {"type": "teleport"})
    with pytest.raises(GameError, match="combat.not_found"):
        await host.intent(
            "55555555-5555-5555-5555-555555555555", OWNER, {"type": "skip"}
        )
    assert len(host.writes) == 0


async def test_recovery_rebuilds_the_same_fight(
    ruleset, store, demo_setup_json
) -> None:
    combat_id = "66666666-6666-6666-6666-666666666666"
    first = _host(ruleset, store)
    await first.create(combat_id, HOTSEAT_MATCH, demo_setup_json)
    for intent in (
        {"type": "wait"},
        {"type": "skip"},
        {"type": "skip"},
        {"type": "skip"},
    ):
        await first.intent(combat_id, OWNER, intent)
    await first.drain()

    second = _host(ruleset, store)  # a restarted worker
    assert await second.start() == 0
    assert second.instances == {}  # nothing is loaded up front
    assert (await second.subscribe(combat_id, OWNER, None))["kind"] == "snapshot"
    live, rebuilt = first.instances[combat_id], second.instances[combat_id]
    assert rebuilt.state == live.state
    assert log_hash(rebuilt.events) == log_hash(live.events)
    # and it keeps playing identically
    await first.intent(combat_id, OWNER, {"type": "skip"})
    await second.intent(combat_id, OWNER, {"type": "skip"})
    assert log_hash(rebuilt.events) == log_hash(live.events)


async def test_recovery_aborts_incompatible_records(
    ruleset, store, demo_setup_json
) -> None:
    from dataclasses import replace

    combat_id = "77777777-7777-7777-7777-777777777777"
    await _host(ruleset, store).create(combat_id, HOTSEAT_MATCH, demo_setup_json)
    changed = replace(ruleset, content_hash="0" * 64)
    assert await _host(changed, store).start() == 1
    [summary] = await store.list_for_user(OWNER)
    assert summary.status == "aborted"


async def test_lazy_recovery_loads_once_and_only_own_active_combats(
    ruleset, store, demo_setup_json
) -> None:
    combat_id = "12121212-1212-1212-1212-121212121212"
    first = _host(ruleset, store)
    await first.create(combat_id, HOTSEAT_MATCH, demo_setup_json)
    await first.intent(combat_id, OWNER, {"type": "wait"})
    await first.drain()

    second = _host(ruleset, store)
    loads = 0
    original = store.load

    async def counting_load(cid: str):
        nonlocal loads
        loads += 1
        return await original(cid)

    store.load = counting_load  # type: ignore[method-assign]
    try:
        replies = await asyncio.gather(
            second.subscribe(combat_id, OWNER, None),
            second.subscribe(combat_id, OWNER, None),
            second.intent(combat_id, OWNER, {"type": "skip"}),
        )
    finally:
        del store.load
    assert loads == 1  # concurrent first touches share one replay
    assert replies[0]["kind"] == "snapshot"

    other_slot = _host(ruleset, store, slot=1)
    with pytest.raises(GameError, match="combat.not_found"):
        await other_slot.subscribe(combat_id, OWNER, None)

    await store.mark(combat_id, "finished")
    with pytest.raises(GameError, match="combat.not_found"):
        await _host(ruleset, store).subscribe(combat_id, OWNER, None)


async def test_subscribe_checks_seats(ruleset, store, demo_setup_json) -> None:
    host = _host(ruleset, store)
    combat_id = "88888888-8888-8888-8888-888888888888"
    await host.create(combat_id, HOTSEAT_MATCH, demo_setup_json)
    assert (await host.subscribe(combat_id, OWNER, None))["kind"] == "snapshot"
    await host.intent(combat_id, OWNER, {"type": "wait"})
    assert (await host.subscribe(combat_id, OWNER, 1))["kind"] == "events"
    with pytest.raises(GameError, match="combat.not_a_participant"):
        await host.subscribe(combat_id, 2, None)


async def test_idle_combats_are_abandoned(ruleset, store, demo_setup_json) -> None:
    clock = FakeClock()
    host = _host(ruleset, store, clock=clock)
    combat_id = "99999999-9999-9999-9999-999999999999"
    await host.create(combat_id, HOTSEAT_MATCH, demo_setup_json)
    clock.advance(3599)
    await host.sweep()
    assert combat_id in host.instances
    clock.advance(2)
    await host.sweep()
    assert combat_id not in host.instances
    [summary] = await store.list_for_user(OWNER)
    assert summary.status == "abandoned"


async def test_write_behind_keeps_order_and_retries() -> None:
    written: list[list[int]] = []
    fail = {"once": True}

    async def flush(batch: list[int]) -> None:
        if fail.pop("once", False):
            raise RuntimeError("db down")
        written.append(batch)

    buffer: WriteBehindBuffer[int] = WriteBehindBuffer(flush, max_batch=2)
    buffer.extend([1, 2, 3])
    with pytest.raises(RuntimeError):
        await buffer.flush()
    assert len(buffer) == 3  # nothing lost
    buffer.add(4)
    await buffer.flush()
    assert written == [[1, 2], [3, 4]] and len(buffer) == 0
