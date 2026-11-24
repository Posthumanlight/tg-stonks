"""One scenario per content ability: the ability must visibly change the outcome.

`test_every_ability_has_a_scenario` fails when a new ability is added without one.
"""

from collections.abc import Callable
from dataclasses import replace

import pytest

from app.combat.ground.actions import Attack, Move, UseAbility
from app.combat.ground.engine import IllegalAction, apply_action, legal_actions
from app.combat.ground.events import AttackResolved, HitResolved, Rolled
from app.combat.ground.los import base_sight
from app.combat.ground.view import BoardView

from .helpers import activate, board, resolver, start

SCENARIOS: dict[str, Callable] = {}


def scenario(*ability_ids: str) -> Callable:
    def register(func: Callable) -> Callable:
        for aid in ability_ids:
            SCENARIOS[aid] = func
        return func

    return register


def _attack(ruleset, state, rng, uid, weapon, target):
    state = activate(ruleset, state, uid)
    return apply_action(ruleset, state, Attack(weapon, target), rng, strict=True)


@scenario("anti")
def scenario_anti(ruleset) -> None:
    # rail lance: anti_tank vs vehicle (150%) × anti-vehicle (150%) = 2.25 × roll
    state, _, rng = start(
        ruleset, [("line_troopers", 0, (0, 0)), ("bastion_walker", 1, (5, 0))]
    )
    state, events = _attack(ruleset, state, rng, 0, "rail_lance", 1)
    roll = next(e for e in events if isinstance(e, Rolled) and e.roll == "dice").result
    hit = next(e for e in events if isinstance(e, HitResolved))
    assert hit.damage in (int(roll * 9 / 4), int(roll * 9 / 4) + 1)


@scenario("assault")
def scenario_assault(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("bastion_walker", 0, (0, 0)), ("spitter_brood", 1, (8, 0))]
    )
    state, _ = _attack(ruleset, state, rng, 1, "spine_spitter", 0)
    assert not state.active.movement_locked


@scenario("heavy")
def scenario_heavy(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("line_troopers", 0, (0, 0)), ("bastion_walker", 1, (8, 0))]
    )
    state = activate(ruleset, state, 0)
    state, _ = apply_action(ruleset, state, Move(((0, 1),)), rng, strict=True)
    with pytest.raises(IllegalAction, match="heavy_moved"):
        apply_action(ruleset, state, Attack("rail_lance", 1), rng, strict=True)


@scenario("blast")
def scenario_blast(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("bastion_walker", 0, (0, 0)), ("ravager_swarm", 1, (4, 0), 21)]
    )
    state, events = _attack(ruleset, state, rng, 0, "flame_projector", 1)
    resolved = next(e for e in events if isinstance(e, AttackResolved))
    assert resolved.hits == 1 + 21 // 3


@scenario("ignores_cover")
def scenario_ignores_cover(ruleset) -> None:
    rows = ["........"] * 8
    rows[0] = "....f..."
    state, _, rng = start(
        ruleset,
        [("bastion_walker", 0, (0, 0)), ("warden", 1, (4, 0))],
        board_=board(rows),
    )
    assert base_sight(BoardView(ruleset, state), 0, 1).cover
    state, events = _attack(ruleset, state, rng, 0, "flame_projector", 1)
    assert all(not e.cover for e in events if isinstance(e, HitResolved))


@scenario("indirect")
def scenario_indirect(ruleset) -> None:
    rows = ["....#..."] * 8
    state, _, rng = start(
        ruleset,
        [("bastion_walker", 0, (0, 0)), ("ravager_swarm", 1, (7, 0))],
        board_=board(rows),
    )
    assert not base_sight(BoardView(ruleset, state), 0, 1).los
    state, events = _attack(ruleset, state, rng, 0, "mortar", 1)
    assert all(e.cover for e in events if isinstance(e, HitResolved))


@scenario("reach")
def scenario_reach(ruleset) -> None:
    state, _, rng = start(ruleset, [("brood_tyrant", 0, (0, 0)), ("warden", 1, (4, 0))])
    state = activate(ruleset, state, 0)
    attacks = {(a.weapon, a.target) for a in legal_actions(ruleset, state).attacks}
    assert ("crusher_mandibles", 1) not in attacks  # distance 3
    state = replace(state, units=(state.unit(0), replace(state.unit(1), origin=(3, 0))))
    attacks = {(a.weapon, a.target) for a in legal_actions(ruleset, state).attacks}
    assert ("crusher_mandibles", 1) in attacks  # distance 2 with reach 1


@scenario("regenerate")
def scenario_regenerate(ruleset) -> None:
    state, _, _ = start(
        ruleset, [("brood_tyrant", 0, (0, 0)), ("heavy_team", 1, (9, 9))]
    )
    state = state.with_unit(replace(state.unit(0), wounded=(0, 5)))
    from app.combat.ground import turn_order

    res = resolver(ruleset, replace(state, active=None))
    turn_order.begin_activation(res, 0)
    assert res.state.unit(0).wounded == (0, 6)


@scenario("bodyguard")
def scenario_bodyguard(ruleset) -> None:
    units = [
        ("warden", 0, (2, 2)),
        ("heavy_team", 0, (3, 2)),
        ("line_troopers", 1, (2, 7)),
    ]
    state, _, rng = start(ruleset, units)
    state, events = _attack(ruleset, state, rng, 2, "pulse_rifle", 0)
    hits = [e for e in events if isinstance(e, HitResolved)]
    assert hits and all(e.target == 1 for e in hits)
    assert state.unit(0).wounded is None and state.unit(0).models == 1


@scenario("rally_cry")
def scenario_rally_cry(ruleset) -> None:
    units = [
        ("line_troopers", 0, (0, 0)),
        ("warden", 0, (2, 2)),
        ("ravager_swarm", 1, (11, 11)),
    ]
    state, _, _ = start(ruleset, units)
    res = resolver(ruleset, state)
    assert res.effective_stat(0, "movement") == 7
    assert res.effective_stat(1, "movement") == 6  # not on itself
    res.state = state.with_unit(replace(state.unit(1), origin=(6, 6)))
    assert res.effective_stat(0, "movement") == 6


@scenario("disengage", "fall_back")
def scenario_disengage(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("line_troopers", 0, (3, 3)), ("ravager_swarm", 1, (4, 3), 30)]
    )
    state = activate(ruleset, state, 0)
    state, _ = apply_action(ruleset, state, UseAbility("fall_back"), rng, strict=True)
    state, events = apply_action(ruleset, state, Move(((2, 3),)), rng, strict=True)
    assert not any(e.kind == "attack_declared" for e in events)
    assert state.unit(0).models == 10


@scenario("smoke_charge")
def scenario_smoke_charge(ruleset) -> None:
    units = [("line_troopers", 0, (0, 3)), ("warden", 1, (7, 3))]
    state, _, rng = start(ruleset, units, board_=board(["........"] * 8))
    assert base_sight(BoardView(ruleset, state), 0, 1).los
    state = activate(ruleset, state, 0)
    state, _ = apply_action(
        ruleset,
        state,
        UseAbility("smoke_charge", target_square=(4, 3)),
        rng,
        strict=True,
    )
    assert len(state.overlays) == 9
    assert not base_sight(BoardView(ruleset, state), 0, 1).los
    with pytest.raises(IllegalAction, match="cooldown"):
        apply_action(
            ruleset,
            state,
            UseAbility("smoke_charge", target_square=(4, 3)),
            rng,
            strict=True,
        )


@scenario("frag_charge")
def scenario_frag_charge(ruleset) -> None:
    units = [
        ("warden", 0, (0, 0)),
        ("heavy_team", 1, (4, 4)),
        ("ravager_swarm", 1, (11, 11)),
    ]
    state, _, rng = start(ruleset, units)
    state = activate(ruleset, state, 0)
    state, events = apply_action(
        ruleset,
        state,
        UseAbility("frag_charge", target_square=(4, 4)),
        rng,
        strict=True,
    )
    assert ruleset.content.units["heavy_team"].hp * 3 > res_hp(state, 1)
    assert state.unit(0).models == 1  # the warden was outside the blast
    state = activate(ruleset, state, 0)
    with pytest.raises(IllegalAction, match="no_uses"):
        apply_action(
            ruleset,
            state,
            UseAbility("frag_charge", target_square=(4, 4)),
            rng,
            strict=True,
        )


def res_hp(state, uid: int) -> int:
    unit = state.unit(uid)
    total = sum(g.alive * g.hp for g in unit.groups)
    if unit.wounded is not None:
        total -= unit.groups[unit.wounded[0]].hp - unit.wounded[1]
    return total


def test_every_ability_has_a_scenario(ruleset) -> None:
    assert set(ruleset.content.abilities) <= set(SCENARIOS), set(
        ruleset.content.abilities
    ) - set(SCENARIOS)


@pytest.mark.parametrize("ability", sorted(SCENARIOS))
def test_scenario(ruleset, ability: str) -> None:
    SCENARIOS[ability](ruleset)
