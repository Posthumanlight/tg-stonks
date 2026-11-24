from dataclasses import replace

import pytest

from app.combat.ground.actions import Attack, Skip, Wait
from app.combat.ground.engine import IllegalAction, apply_action
from app.combat.ground.events import ActivationStarted, RoundStarted
from app.combat.ground.ruleset import ruleset_from_raw

from .helpers import activate, kinds, start


def _run(ruleset, state, rng, actions):
    log = []
    for action in actions:
        state, events = apply_action(ruleset, state, action, rng, strict=True)
        log += events
    return state, log


def _activations(events) -> list[int]:
    return [e.unit for e in events if isinstance(e, ActivationStarted)]


def test_speed_order(ruleset) -> None:
    units = [
        ("heavy_team", 0, (0, 0)),
        ("warden", 0, (0, 2)),
        ("ravager_swarm", 1, (11, 11)),
    ]
    state, events, _ = start(ruleset, units)
    assert state.round == 1
    assert state.round_order == (2, 1, 0)  # speed 8, 6, 3
    assert state.active.uid == 2
    assert _activations(events) == [2]


def test_ties_rotate_between_sides_each_round(ruleset) -> None:
    units = [("warden", 0, (0, 0)), ("warden", 1, (5, 5)), ("warden", 2, (10, 10))]
    state, events, rng = start(ruleset, units, seed=3)
    sides = state.side_order
    assert sorted(sides) == [0, 1, 2]
    assert [state.unit(u).side for u in state.round_order] == list(sides)
    state, log = _run(ruleset, state, rng, [Skip()] * 3)
    round2 = next(e for e in log if isinstance(e, RoundStarted))
    assert [state.unit(u).side for u in round2.order] == list(sides[1:] + sides[:1])


def test_wait_queue_runs_slowest_first(ruleset) -> None:
    units = [
        ("ravager_swarm", 1, (11, 11)),
        ("warden", 0, (0, 2)),
        ("heavy_team", 0, (0, 0)),
    ]
    state, _, rng = start(ruleset, units)
    assert state.round_order == (0, 1, 2)
    state, log = _run(ruleset, state, rng, [Wait(), Wait(), Skip()])
    assert _activations(log) == [1, 2, 1]  # after the swarm and warden waited
    assert state.active.uid == 1  # warden (speed 6) before the swarm (speed 8)
    with pytest.raises(IllegalAction, match="wait"):
        apply_action(ruleset, state, Wait(), rng, strict=True)  # once per round
    state, log = _run(ruleset, state, rng, [Skip()])
    assert state.active.uid == 0


def test_wait_only_before_acting(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("warden", 0, (0, 0)), ("ravager_swarm", 1, (11, 11))]
    )
    state = activate(ruleset, state, 0)
    from app.combat.ground.actions import Move

    state, _ = apply_action(ruleset, state, Move(((1, 1),)), rng, strict=True)
    with pytest.raises(IllegalAction, match="wait"):
        apply_action(ruleset, state, Wait(), rng, strict=True)


def test_dead_units_leave_the_queue(ruleset) -> None:
    units = [
        ("ravager_swarm", 1, (11, 11)),
        ("warden", 0, (0, 2)),
        ("heavy_team", 0, (0, 0)),
    ]
    state, _, rng = start(ruleset, units)
    heavy = state.unit(2)
    dead = replace(heavy, groups=tuple(replace(g, alive=0) for g in heavy.groups))
    state = state.with_unit(dead)
    state, log = _run(ruleset, state, rng, [Skip(), Skip()])
    assert _activations(log) == [
        1,
        0,
    ]  # heavy team skipped; round 2 starts with the swarm
    assert state.round == 2


def test_activation_auto_ends_without_options(ruleset) -> None:
    units = [("warden", 0, (5, 5)), ("ravager_swarm", 1, (6, 5), 30)]
    state, _, rng = start(ruleset, units)
    state = activate(ruleset, state, 0)
    state, log = _run(
        ruleset, state, rng, [Attack("sidearm", 1), Attack("shock_maul", 1)]
    )
    assert "activation_ended" in kinds(log)  # no AP, movement locked
    assert state.active is None or state.active.uid != 0


def test_annihilation_ends_the_combat(ruleset) -> None:
    units = [("bastion_walker", 0, (0, 0)), ("warden", 1, (3, 0))]
    state, _, rng = start(ruleset, units)
    state = activate(ruleset, state, 0)
    for _ in range(10):
        state = state.with_unit(replace(state.unit(1), wounded=(0, 1)))
        state = activate(ruleset, state, 0)
        state, log = apply_action(
            ruleset, state, Attack("flame_projector", 1), rng, strict=True
        )
        if state.outcome is not None:
            break
    assert state.outcome is not None
    assert state.outcome.winners == (0,) and state.outcome.reason == "annihilation"
    assert log[-1].kind == "combat_ended"
    with pytest.raises(IllegalAction, match="over"):
        apply_action(ruleset, state, Skip(), rng)


def test_round_limit_points(raw) -> None:
    raw["rules"]["round_limit"] = 2
    rs = ruleset_from_raw(raw)
    state, _, rng = start(rs, [("warden", 0, (0, 0)), ("warden", 1, (11, 11))])
    state, log = _run(rs, state, rng, [Skip()] * 4)
    assert state.outcome.reason == "round_limit"
    assert state.outcome.draw and state.outcome.winners == (0, 1)

    state, _, rng = start(rs, [("warden", 0, (0, 0)), ("heavy_team", 1, (11, 11))])
    state, _ = _run(rs, state, rng, [Skip()] * 4)
    assert state.outcome.winners == (1,) and not state.outcome.draw  # 110 vs 80 points
