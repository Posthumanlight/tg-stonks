"""Determinism: a combat is a pure function of (setup, seed, content, actions)."""

import random

import pytest

from app.combat.ground.actions import Attack, Move, Skip, UseAbility, Wait
from app.combat.ground.engine import (
    COMBAT_RULES_VERSION,
    CombatRecord,
    apply_action,
    legal_actions,
    replay,
    start_combat,
)
from app.combat.ground.events import log_hash
from app.combat.ground.setup import CombatSetup, UnitSetup
from app.combat.ground.board import Board

SETUP = CombatSetup(
    Board.filled(20, 20),
    (
        UnitSetup("line_troopers", 0, (2, 2)),
        UnitSetup("heavy_team", 0, (4, 1)),
        UnitSetup("warden", 0, (3, 4)),
        UnitSetup("bastion_walker", 0, (1, 6)),
        UnitSetup("ravager_swarm", 1, (15, 15)),
        UnitSetup("spitter_brood", 1, (17, 13)),
        UnitSetup("brood_tyrant", 1, (13, 17)),
    ),
)


def play(ruleset, seed: int, chooser_seed: int, max_actions: int = 400):
    """A seeded random player choosing among legal actions, biased toward fighting."""
    rng = random.Random(seed)
    chooser = random.Random(chooser_seed)
    state, log = start_combat(ruleset, SETUP, rng, strict=True)
    actions = []
    while state.outcome is None and len(actions) < max_actions:
        options = legal_actions(ruleset, state)
        choices: list = [Attack(a.weapon, a.target) for a in options.attacks] * 3
        for ability in options.abilities:
            if ability.target_units:
                choices.append(
                    UseAbility(ability.ability, target_unit=ability.target_units[0])
                )
            else:
                choices.append(
                    UseAbility(
                        ability.ability, target_square=ability.target_squares[-1]
                    )
                )
        if options.moves:
            me = state.unit(options.unit)
            enemies = [u for u in state.living() if u.side != me.side]
            best = min(
                options.moves,
                key=lambda m: min(
                    abs(m.destination[0] - e.origin[0])
                    + abs(m.destination[1] - e.origin[1])
                    for e in enemies
                ),
            )
            choices += [Move(best.path)] * 2
        if options.can_wait:
            choices.append(Wait())
        choices.append(Skip())
        action = chooser.choice(choices)
        actions.append(action)
        state, events = apply_action(ruleset, state, action, rng, strict=True)
        log += events
    return state, log, tuple(actions)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_replay_reproduces_the_fight(ruleset, seed: int) -> None:
    state, log, actions = play(ruleset, seed, seed + 100)
    assert state.outcome is not None
    record = CombatRecord(
        SETUP, seed, ruleset.content_hash, COMBAT_RULES_VERSION, actions
    )
    replayed_state, replayed_log = replay(ruleset, record, strict=True)
    assert replayed_state == state
    assert log_hash(replayed_log) == log_hash(log)


def test_same_inputs_same_log(ruleset) -> None:
    a = play(ruleset, 5, 6)
    b = play(ruleset, 5, 6)
    assert log_hash(a[1]) == log_hash(b[1])
    assert log_hash(play(ruleset, 7, 6)[1]) != log_hash(a[1])


def test_replay_refuses_other_content(ruleset) -> None:
    record = CombatRecord(SETUP, 1, "0" * 64, COMBAT_RULES_VERSION, ())
    with pytest.raises(ValueError, match="content"):
        replay(ruleset, record)


# Golden fight: update ONLY for intentional rule/content changes. A rules change that
# alters outcomes also bumps COMBAT_RULES_VERSION (docs/combat-ground.md "Versioning").
GOLDEN_SEED = 42
GOLDEN_HASH = "1135bb2cd643defbf00e2cd893d0751f65efb1b8eb57993360b527d3f89d21df"


def test_golden_fight(ruleset) -> None:
    state, log, _ = play(ruleset, GOLDEN_SEED, 4242)
    assert state.outcome is not None
    assert log_hash(log) == GOLDEN_HASH
