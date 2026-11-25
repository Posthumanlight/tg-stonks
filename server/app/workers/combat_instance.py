"""One combat: the pure engine plus seats, an event log and intent translation.

Seats come from the combat's `Match` (hotseat: the owner holds every side; online: one
side per player).

No I/O and no transport (persistence and delivery belong to `CombatHost`). Intents are
handled synchronously, so on the worker's event loop two of them can never interleave —
no lock is needed.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass

from app.combat.ground.actions import (
    Action,
    Attack,
    Concede,
    Move,
    Skip,
    UseAbility,
    Wait,
)
from app.combat.ground.engine import (
    IllegalAction,
    apply_action,
    legal_actions,
    resume,
    start_combat,
)
from app.combat.ground.events import ActivationStarted, Event
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.serialize import action_to_json, outcome_to_json
from app.combat.ground.setup import CombatSetup
from app.combat.match import Match
from app.protocol.combat import (
    AbilityIntent,
    AttackIntent,
    CombatIntent,
    CombatSnapshot,
    CombatUpdate,
    MoveIntent,
    PlayerView,
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


class CombatInstance:
    def __init__(
        self,
        combat_id: str,
        match: Match,
        ruleset: CombatRuleset,
        setup: CombatSetup,
        seed: int,
        *,
        actions: Sequence[Action] = (),
    ) -> None:
        if not match.seats:  # an older record: the owner holds every side
            match = Match.hotseat(match.owner_user_id, (u.side for u in setup.units))
        self.combat_id = combat_id
        self.match = match
        self.ruleset = ruleset
        self.setup = setup
        self.seed = seed
        self.seats = match.seat_map()
        if actions:
            self.state, log, self.rng = resume(ruleset, setup, seed, actions)
        else:
            self.rng = random.Random(seed)
            self.state, log = start_combat(ruleset, setup, self.rng)
        self.events: list[Event] = []
        self.activations = 0  # activations started so far (the timer's key)
        self._log(log)
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

    @property
    def timer_s(self) -> int | None:
        return self.match.timer_s

    def seated(self, user_id: int) -> bool:
        return user_id in self.seats.values()

    def side_of(self, user_id: int) -> int:
        """The user's one side (online play). Hotseat owners hold several: refused."""
        sides = [side for side, holder in self.seats.items() if holder == user_id]
        if len(sides) != 1:
            raise GameError("combat.not_a_participant", 403)
        return sides[0]

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
        except IllegalAction as exc:
            raise GameError(exc.reason, 400) from exc
        return self._apply(action)

    def concede(self, user_id: int) -> IntentResult:
        """The user's side gives up (online surrender); the other side wins."""
        if self.finished:
            raise GameError("combat.finished", 409)
        return self._apply(Concede(self.side_of(user_id)))

    def timeout(self) -> IntentResult | None:
        """The activation timer ran out: skip for the active unit's player. Recorded
        like any Skip, so replays are unaffected. None when nobody is active."""
        if self.finished or self.state.active is None:
            return None
        return self._apply(Skip())

    def _apply(self, action: Action) -> IntentResult:
        try:
            self.state, events = apply_action(
                self.ruleset, self.state, action, self.rng
            )
        except IllegalAction as exc:
            raise GameError(exc.reason, 400) from exc
        from_seq = self.seq
        self._log(events)
        self.actions.append(action)
        return IntentResult(
            update=self._update(from_seq),
            action=action_to_json(action),
            action_seq=len(self.actions) - 1,
            finished=self.finished,
        )

    def _log(self, events: Sequence[Event]) -> None:
        self.events.extend(events)
        self.activations += sum(isinstance(e, ActivationStarted) for e in events)

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
            board=board_view(
                self.state,
                self.setup.factions,
                [
                    PlayerView(side=s.side, user_id=s.user_id, name=s.name)
                    for s in self.match.seats
                ],
            ),
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
