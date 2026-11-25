"""CombatInstance (pure): seats, intents, event log, catch-up, resume, plus the codec."""

import random

import pytest

from app.combat.ground.actions import Attack, Move, Skip, UseAbility, Wait
from app.combat.ground.events import log_hash
from app.combat.ground.serialize import (
    action_from_json,
    action_to_json,
    setup_from_json,
    setup_to_json,
)
from app.combat.ground.deployment import load_demo_setup
from app.protocol.combat import MoveIntent, SkipIntent, WaitIntent
from app.shared.errors import GameError
from app.workers.combat_instance import CombatInstance

OWNER = 1


def _instance(ruleset, seed: int = 7, actions=()) -> CombatInstance:
    return CombatInstance(
        "c-1",
        OWNER,
        "hotseat",
        ruleset,
        load_demo_setup(ruleset),
        seed,
        actions=actions,
    )


@pytest.mark.parametrize(
    "action",
    [
        Move(((1, 2), (2, 3))),
        Attack("pulse_rifle", 4),
        UseAbility("smoke_charge", None, (5, 6)),
        UseAbility("fall_back", 0, None),
        Wait(),
        Skip(),
    ],
)
def test_action_codec_round_trips(action) -> None:
    assert action_from_json(action_to_json(action)) == action


@pytest.mark.parametrize(
    "bad", [{}, {"type": "fly"}, {"type": "attack"}, {"type": "move", "path": [[1]]}]
)
def test_action_codec_rejects_garbage(bad) -> None:
    with pytest.raises(ValueError):
        action_from_json(bad)


def test_setup_codec_round_trips(ruleset) -> None:
    setup = load_demo_setup(ruleset)
    assert setup_from_json(setup_to_json(setup)) == setup


def test_hotseat_owner_holds_every_side(ruleset) -> None:
    instance = _instance(ruleset)
    assert set(instance.seats.values()) == {OWNER}
    assert instance.seated(OWNER) and not instance.seated(2)
    with pytest.raises(GameError, match="combat.not_your_turn"):
        instance.handle(2, SkipIntent(type="skip"))


def test_intents_update_log_and_state(ruleset) -> None:
    instance = _instance(ruleset)
    seq0, active = instance.seq, instance.state.active.uid
    result = instance.handle(OWNER, WaitIntent(type="wait"))
    assert result.update.from_seq == seq0
    assert [e.seq for e in result.update.events] == list(range(seq0, instance.seq))
    assert result.update.view.seq == instance.seq
    assert result.action == {"type": "wait"} and result.action_seq == 0
    assert instance.state.active.uid != active


def test_move_by_destination_uses_the_shown_path(ruleset) -> None:
    instance = _instance(ruleset)
    legal = instance._update(instance.seq).legal
    destination = legal.moves[-1].to
    instance.handle(OWNER, MoveIntent(type="move", to=destination))
    # at the demo's start no enemy is in reach, so the unit lands exactly there
    assert instance.actions[-1].path[-1] == tuple(destination)
    assert instance.state.unit(legal.unit).origin == tuple(destination)


def test_refused_intents_change_nothing(ruleset) -> None:
    instance = _instance(ruleset)
    before = (instance.state, instance.seq, instance.rng.getstate())
    with pytest.raises(GameError, match="move.forbidden"):
        instance.handle(
            OWNER, MoveIntent(type="move", to=(11, 11))  # deep water
        )  # occupied / not legal
    assert (instance.state, instance.seq, instance.rng.getstate()) == before


def test_catch_up_or_snapshot(ruleset) -> None:
    instance = _instance(ruleset)
    instance.handle(OWNER, WaitIntent(type="wait"))
    update = instance.catch_up(2, max_events=500)
    assert update is not None and update.from_seq == 2
    assert instance.catch_up(None, 500) is None  # new client → snapshot
    assert instance.catch_up(instance.seq + 5, 500) is None  # nonsense → snapshot
    assert instance.catch_up(0, max_events=1) is None  # too far behind → snapshot


def test_resume_reproduces_the_live_fight(ruleset) -> None:
    live = _instance(ruleset, seed=11)
    chooser = random.Random(3)
    for _ in range(25):
        if live.finished:
            break
        legal = live._update(live.seq).legal
        options = [SkipIntent(type="skip"), WaitIntent(type="wait")]
        if legal.moves:
            options.append(MoveIntent(type="move", to=chooser.choice(legal.moves).to))
        for intent in [chooser.choice(options), SkipIntent(type="skip")]:
            try:
                live.handle(OWNER, intent)
                break
            except GameError:
                continue
    rebuilt = _instance(ruleset, seed=11, actions=live.actions)
    assert rebuilt.state == live.state
    assert log_hash(rebuilt.events) == log_hash(live.events)
    assert (
        rebuilt.rng.getstate() == live.rng.getstate()
    )  # the fight continues identically
