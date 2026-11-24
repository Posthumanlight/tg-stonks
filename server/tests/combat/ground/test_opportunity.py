from app.combat.ground.actions import Move, UseAbility
from app.combat.ground.engine import apply_action, legal_actions
from app.combat.ground.events import AttackDeclared, UnitMoved
from app.combat.ground.ruleset import ruleset_from_raw

from .helpers import activate, start


def _move(ruleset, state, rng, path):
    return apply_action(ruleset, state, Move(tuple(path)), rng, strict=True)


def _opportunity(events) -> list[AttackDeclared]:
    return [e for e in events if isinstance(e, AttackDeclared) and e.opportunity]


def test_leaving_reach_provokes_once_per_reaction(ruleset) -> None:
    # tyrant (2×2 at 2,2) next to the warden at (4,3)
    state, _, rng = start(ruleset, [("brood_tyrant", 0, (2, 2)), ("warden", 1, (4, 3))])
    state = activate(ruleset, state, 0)
    preview = {m.destination: m.provokes for m in legal_actions(ruleset, state).moves}
    assert preview[(1, 2)] == (1,)
    assert preview[(2, 1)] == ()  # still within reach

    state, events = _move(ruleset, state, rng, [(1, 2), (2, 2), (1, 2)])
    oas = _opportunity(events)
    assert len(oas) == 1 and oas[0].attacker == 1 and oas[0].weapon == "shock_maul"
    # the attack resolves before the first step
    first_move = next(i for i, e in enumerate(events) if isinstance(e, UnitMoved))
    assert events.index(oas[0]) < first_move
    assert state.unit(1).reactions == 0


def test_moving_within_reach_does_not_provoke(ruleset) -> None:
    state, _, rng = start(ruleset, [("warden", 0, (3, 3)), ("warden", 1, (4, 3))])
    state = activate(ruleset, state, 0)
    state, events = _move(ruleset, state, rng, [(3, 4), (4, 4)])
    assert _opportunity(events) == []


def test_units_without_melee_weapons_do_not_react(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("warden", 0, (2, 0)), ("bastion_walker", 1, (3, 0))]
    )
    state = activate(ruleset, state, 0)
    state, events = _move(ruleset, state, rng, [(1, 0), (0, 0)])
    assert _opportunity(events) == []


def test_hit_percent_scales_opportunity_attacks(raw) -> None:
    raw["rules"]["opportunity_attack_hit_percent"] = 0
    rs = ruleset_from_raw(raw)
    state, _, rng = start(rs, [("warden", 0, (3, 3)), ("ravager_swarm", 1, (4, 3))])
    state = activate(rs, state, 0)
    state, events = _move(rs, state, rng, [(2, 3)])
    assert len(_opportunity(events)) == 1
    resolved = [e for e in events if e.kind == "attack_resolved"]
    assert resolved[0].hits == 0 and state.unit(0).models == 1


def test_mover_killed_mid_path_stops(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("line_troopers", 0, (3, 3), 5), ("ravager_swarm", 1, (4, 3), 30)]
    )
    state = activate(ruleset, state, 0)
    state, events = _move(ruleset, state, rng, [(2, 3), (1, 3)])
    assert not state.unit(0).alive
    assert not [e for e in events if isinstance(e, UnitMoved)]
    assert state.outcome is not None and state.outcome.winners == (1,)


def test_fall_back_disengages(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("line_troopers", 0, (3, 3)), ("ravager_swarm", 1, (4, 3), 30)]
    )
    state = activate(ruleset, state, 0)
    state, events = apply_action(
        ruleset, state, UseAbility("fall_back"), rng, strict=True
    )
    assert state.unit(0).has_status("disengage")
    state, events = _move(ruleset, state, rng, [(2, 3), (1, 3)])
    assert _opportunity(events) == []
    assert state.unit(0).origin == (1, 3) and state.unit(0).models == 10
