"""A side's concession (an online player's surrender): ends the fight, replays."""

import random

import pytest

from app.combat.ground import events as ev
from app.combat.ground.actions import Concede, Skip
from app.combat.ground.engine import IllegalAction, apply_action, resume, start_combat
from app.combat.ground.serialize import action_from_json, action_to_json
from tests.combat.ground.test_replay import SETUP


def test_concede_ends_the_fight_for_the_other_side(ruleset) -> None:
    rng = random.Random(7)
    state, _ = start_combat(ruleset, SETUP, rng)
    before = rng.getstate()
    state, events = apply_action(ruleset, state, Concede(1), rng)
    assert rng.getstate() == before  # no dice
    assert state.outcome is not None
    assert (state.outcome.winners, state.outcome.draw, state.outcome.reason) == (
        (0,),
        False,
        "concede",
    )
    assert state.active is None
    assert isinstance(events[-1], ev.CombatEnded)
    with pytest.raises(IllegalAction, match="over"):
        apply_action(ruleset, state, Concede(0), rng)


def test_concede_needs_a_side_in_the_fight(ruleset) -> None:
    rng = random.Random(7)
    state, _ = start_combat(ruleset, SETUP, rng)
    with pytest.raises(IllegalAction, match="concede.forbidden.side"):
        apply_action(ruleset, state, Concede(5), rng)


def test_concede_round_trips_and_replays(ruleset) -> None:
    assert action_from_json(action_to_json(Concede(0))) == Concede(0)
    actions = (Skip(), Concede(0))
    state, log, _ = resume(ruleset, SETUP, 11, actions)
    assert state.outcome is not None and state.outcome.winners == (1,)
    assert isinstance(log[-1], ev.CombatEnded)
