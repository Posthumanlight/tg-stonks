"""One combat: the pure engine plus seats, an event log and intent translation.

No I/O and no transport (persistence and delivery belong to `CombatHost`). Intents are
handled synchronously, so on the worker's event loop two of them can never interleave —
no lock is needed.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass

from app.combat.ground.actions import Action, Attack, Move, Skip, UseAbility, Wait
from app.combat.ground.engine import (
    IllegalAction,
    apply_action,
    legal_actions,
    resume,
    start_combat,
)
from app.combat.ground.events import Event
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.serialize import action_to_json, outcome_to_json
from app.combat.ground.setup import CombatSetup
from app.protocol.combat import (
    AbilityIntent,
    AttackIntent,
    CombatIntent,
    CombatSnapshot,
    CombatUpdate,
    MoveIntent,
    SkipIntent,
    WaitIntent,
    board_view,
    combat_event,
    combat_legal,
    combat_view,
)
from app.shared.errors import GameError


@dataclass(frozen=True, slots=True)
class IntentResult:
    update: CombatUpdate  # pushed to every subscriber
    action: dict  # the engine action as JSON, for the persisted record
    action_seq: int  # its index in the record
    finished: bool


def hotseat_seats(setup: CombatSetup, owner_user_id: int) -> dict[int, int]:
    """Hotseat: the owner holds every side."""
    return {u.side: owner_user_id for u in setup.units}


class CombatInstance:
    def __init__(
        self,
        combat_id: str,
        owner_user_id: int,
        mode: str,
        ruleset: CombatRuleset,
        setup: CombatSetup,
        seed: int,
        *,
        actions: Sequence[Action] = (),
    ) -> None:
        self.combat_id = combat_id
        self.owner_user_id = owner_user_id
        self.mode = mode
        self.ruleset = ruleset
        self.setup = setup
        self.seed = seed
        self.seats = hotseat_seats(setup, owner_user_id)
        if actions:
            self.state, log, self.rng = resume(ruleset, setup, seed, actions)
        else:
            self.rng = random.Random(seed)
            self.state, log = start_combat(ruleset, setup, self.rng)
        self.events: list[Event] = list(log)
        self.actions: list[Action] = list(actions)

    @property
    def seq(self) -> int:
        """Number of events so far (the next event's seq)."""
        return len(self.events)

    @property
    def finished(self) -> bool:
        return self.state.outcome is not None

    def outcome_json(self) -> dict | None:
        return outcome_to_json(self.state.outcome)

    def seated(self, user_id: int) -> bool:
        return user_id in self.seats.values()

    # --- intents -----------------------------------------------------------------------

    def handle(self, user_id: int, intent: CombatIntent) -> IntentResult:
        """Apply one intent. Raises GameError (nothing changes) when it's refused."""
        if self.finished:
            raise GameError("combat.finished", 409)
        active = self.state.active
        if (
            active is None
            or self.seats.get(self.state.unit(active.uid).side) != user_id
        ):
            raise GameError("combat.not_your_turn", 403)
        try:
            action = self._to_action(intent)
            self.state, events = apply_action(
                self.ruleset, self.state, action, self.rng
            )
        except IllegalAction as exc:
            raise GameError(exc.reason, 400) from exc
        from_seq = self.seq
        self.events.extend(events)
        self.actions.append(action)
        return IntentResult(
            update=self._update(from_seq),
            action=action_to_json(action),
            action_seq=len(self.actions) - 1,
            finished=self.finished,
        )

    def _to_action(self, intent: CombatIntent) -> Action:
        match intent:
            case MoveIntent(to=to):
                legal = legal_actions(self.ruleset, self.state)
                option = next(
                    (
                        m
                        for m in (legal.moves if legal else ())
                        if m.destination == tuple(to)
                    ),
                    None,
                )
                if option is None:
                    raise IllegalAction("move.forbidden.blocked")
                return Move(option.path)
            case AttackIntent(weapon=weapon, target=target):
                return Attack(weapon, target)
            case AbilityIntent(ability=ability, target_unit=unit, target_square=square):
                return UseAbility(ability, unit, tuple(square) if square else None)
            case WaitIntent():
                return Wait()
            case SkipIntent():
                return Skip()
        raise IllegalAction("combat.forbidden.unknown_action")

    # --- views -------------------------------------------------------------------------

    def _update(self, from_seq: int) -> CombatUpdate:
        return CombatUpdate(
            combat_id=self.combat_id,
            from_seq=from_seq,
            events=[
                combat_event(seq, self.events[seq]) for seq in range(from_seq, self.seq)
            ],
            view=combat_view(self.combat_id, self.seq, self.state),
            legal=combat_legal(legal_actions(self.ruleset, self.state)),
        )

    def snapshot(self) -> CombatSnapshot:
        return CombatSnapshot(
            board=board_view(self.state, self.setup.factions),
            view=combat_view(self.combat_id, self.seq, self.state),
            legal=combat_legal(legal_actions(self.ruleset, self.state)),
        )

    def catch_up(self, last_seq: int | None, max_events: int) -> CombatUpdate | None:
        """Events since `last_seq` for a reconnecting client, or None when a snapshot is
        needed instead (unknown position or too far behind)."""
        if (
            last_seq is None
            or not 0 <= last_seq <= self.seq
            or self.seq - last_seq > max_events
        ):
            return None
        return self._update(last_seq)
