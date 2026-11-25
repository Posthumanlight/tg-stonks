"""One contract, two backends (Liskov): InProcessBackend and ProcessBackend must behave
the same. The process variant spawns real worker processes (marked `slow`)."""

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from app.combat.match import PVP, Match, Seat
from app.services.combat_backend import InProcessBackend, ProcessBackend
from app.shared.clock import FakeClock, SystemClock
from app.shared.errors import GameError
from app.workers.supervisor import Supervisor, SupervisorConfig

OWNER = 1
HOTSEAT_MATCH = Match.hotseat(OWNER, (0, 1))
COMBAT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture(params=["in_process", pytest.param("process", marks=pytest.mark.slow)])
async def backend(request, ruleset, store, db_url) -> AsyncIterator:
    if request.param == "in_process":
        instance = InProcessBackend(ruleset, store, FakeClock(), slots=2)
    else:
        config = SupervisorConfig(
            workers=2,
            database_url=db_url,
            pool_size=1,
            idle_timeout_s=3600,
            flush_interval_s=0.1,
        )
        instance = ProcessBackend(Supervisor(config, SystemClock()))
    pushes: list = []
    instance.on_push(lambda cid, update: pushes.append((cid, update)))
    instance.pushes = pushes  # type: ignore[attr-defined]
    await instance.start()
    try:
        yield instance
    finally:
        await instance.stop()


async def _wait_for(condition, timeout: float = 5.0) -> None:
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


async def test_create_intent_push_subscribe(backend, demo_setup_json) -> None:
    assert backend.slots == 2
    creating = asyncio.ensure_future(
        backend.create(1, COMBAT, HOTSEAT_MATCH, demo_setup_json)
    )
    await asyncio.sleep(0)
    # Counted from the moment of placement, so a burst of creates spreads out.
    assert backend.loads()[1] == 1
    snapshot = await creating
    assert backend.loads()[1] == 1
    assert snapshot["view"]["combat_id"] == COMBAT and snapshot["legal"] is not None

    await backend.intent(1, COMBAT, OWNER, {"type": "wait"})
    await _wait_for(lambda: backend.pushes)
    combat_id, update_json = backend.pushes[0]
    update = json.loads(update_json)  # pushes are pre-serialized JSON text
    assert combat_id == COMBAT and update["events"] and update["view"]["seq"] > 0

    reply = await backend.subscribe(1, COMBAT, OWNER, None)
    assert reply["kind"] == "snapshot"
    await _wait_for(lambda: backend.loads()[1] == 1)  # workers report load periodically


async def test_errors_cross_the_boundary_unchanged(backend, demo_setup_json) -> None:
    await backend.create(0, COMBAT, HOTSEAT_MATCH, demo_setup_json)
    with pytest.raises(GameError) as not_your_turn:
        await backend.intent(0, COMBAT, 2, {"type": "skip"})
    assert (not_your_turn.value.reason_key, not_your_turn.value.status) == (
        "combat.not_your_turn",
        403,
    )
    with pytest.raises(GameError, match="combat.not_found"):
        await backend.intent(1, COMBAT, OWNER, {"type": "skip"})  # wrong slot
    with pytest.raises(GameError, match="move.forbidden"):
        await backend.intent(0, COMBAT, OWNER, {"type": "move", "to": [11, 11]})


async def test_close_abandons_the_combat(backend, store, demo_setup_json) -> None:
    await backend.create(0, COMBAT, HOTSEAT_MATCH, demo_setup_json)
    await backend.intent(0, COMBAT, OWNER, {"type": "skip"})
    await backend.close(0, COMBAT, "player")
    stored = await store.load(COMBAT)
    assert stored is not None and stored.status == "abandoned"
    assert len(stored.actions) == 1  # pending actions were flushed first
    with pytest.raises(GameError, match="combat.not_found"):
        await backend.intent(0, COMBAT, OWNER, {"type": "skip"})


async def test_concede_finishes_an_online_combat(
    backend, store, demo_setup_json
) -> None:
    match = Match(OWNER, PVP, (Seat(0, OWNER, "a"), Seat(1, 2, "b")), timer_s=45)
    snapshot = await backend.create(0, COMBAT, match, demo_setup_json)
    assert [p["user_id"] for p in snapshot["board"]["players"]] == [OWNER, 2]
    assert snapshot["deadline_ms"] is not None
    await backend.concede(0, COMBAT, 2)
    await _wait_for(lambda: bool(backend.pushes))
    outcome = json.loads(backend.pushes[-1][1])["view"]["outcome"]
    assert outcome["winners"] == [0] and outcome["reason"] == "concede"
    stored = await store.load(COMBAT)
    assert stored is not None and stored.status == "finished"
    assert stored.match == match


@pytest.mark.slow
async def test_killed_worker_recovers_its_combats(
    ruleset, store, db_url, demo_setup_json
) -> None:
    config = SupervisorConfig(
        workers=1,
        database_url=db_url,
        pool_size=1,
        idle_timeout_s=3600,
        flush_interval_s=0.05,
    )
    supervisor = Supervisor(config, SystemClock())
    backend = ProcessBackend(supervisor)
    await backend.start()
    try:
        await backend.create(0, COMBAT, HOTSEAT_MATCH, demo_setup_json)
        await backend.intent(0, COMBAT, OWNER, {"type": "wait"})
        before = await backend.subscribe(0, COMBAT, OWNER, None)
        await asyncio.sleep(0.3)  # let write-behind flush

        supervisor.kill_worker_for_tests(0)
        with pytest.raises(GameError, match="combat.unavailable"):
            for _ in range(100):  # until the supervisor notices
                await backend.subscribe(0, COMBAT, OWNER, None)
                await asyncio.sleep(0.05)

        for _ in range(200):  # restarted and recovered by replay
            try:
                after = await backend.subscribe(0, COMBAT, OWNER, None)
                break
            except GameError:
                await asyncio.sleep(0.1)
        else:
            raise AssertionError("worker did not come back")
        assert after["snapshot"]["view"] == before["snapshot"]["view"]
    finally:
        await backend.stop()
