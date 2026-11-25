"""Client-facing combat views (docs/protocol.md). Built once, in the combat worker, from
engine state; the gateway forwards the JSON untouched. The client renders state from
`CombatView` and uses events only for animation and the log — no rules on the client.
"""

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import Field

from app.combat.ground.engine import LegalActions
from app.combat.ground.events import Event, event_to_dict
from app.combat.ground.state import CombatState
from app.combat.ground.serialize import outcome_to_json
from app.protocol.base import ProtocolModel

Pair = tuple[int, int]


class PlayerView(ProtocolModel):
    """Who holds a side. The client compares `user_id` with its own to know which
    sides it may act for."""

    side: int
    user_id: int
    name: str  # "" in hotseat (the labels use the faction then)


class BoardView(ProtocolModel):
    """Sent once with a snapshot: terrain and seats never change during a combat."""

    width: int
    height: int
    terrain: list[str]  # row-major terrain ids
    factions: list[str] | None = (
        None  # faction id per side (side labels); null: unknown
    )
    players: list[PlayerView] | None = None  # null outside a combat (the builder)


class GroupView(ProtocolModel):
    role: str
    alive: int
    initial: int
    hp: int


class StatusView(ProtocolModel):
    status: str
    rounds_left: int
    stacks: int


class UnitView(ProtocolModel):
    uid: int
    unit_type: str
    side: int
    origin: Pair
    size: int
    models: int
    groups: list[GroupView]
    wounded: Pair | None  # (group index, hp left)
    statuses: list[StatusView]
    reactions: int


class OverlayView(ProtocolModel):
    square: Pair
    overlay: str
    rounds_left: int


class ActiveView(ProtocolModel):
    uid: int
    movement_left: int
    ap_left: int
    weapons_used: list[str]
    moved: bool
    attacked: bool
    movement_locked: bool
    acted: bool


class OutcomeView(ProtocolModel):
    winners: list[int]
    draw: bool
    reason: str


class CombatView(ProtocolModel):
    combat_id: str
    seq: int  # number of events so far; resync point
    round: int
    units: list[UnitView]
    overlays: list[OverlayView]
    round_order: list[int]
    queue: list[int]
    wait_queue: list[int]
    active: ActiveView | None
    outcome: OutcomeView | None


class MoveOptionView(ProtocolModel):
    to: Pair
    cost: int
    provokes: list[int]  # enemies that get an opportunity attack on the way


class AttackOptionView(ProtocolModel):
    weapon: str
    target: int
    ap_cost: int
    cover: bool


class AbilityOptionView(ProtocolModel):
    ability: str
    ap_cost: int
    target_units: list[int]
    target_squares: list[Pair]


class CombatLegal(ProtocolModel):
    unit: int
    moves: list[MoveOptionView]
    attacks: list[AttackOptionView]
    abilities: list[AbilityOptionView]
    can_wait: bool


class CombatEvent(ProtocolModel):
    seq: int
    type: str
    data: dict[str, Any]


class CombatSnapshot(ProtocolModel):
    board: BoardView
    view: CombatView
    legal: CombatLegal | None
    deadline_ms: int | None = None  # the activation timer's end (epoch ms); null: none


class CombatUpdate(ProtocolModel):
    """Pushed after every action: what happened, the new state, what's legal next."""

    combat_id: str
    from_seq: int
    events: list[CombatEvent]
    view: CombatView
    legal: CombatLegal | None
    deadline_ms: int | None = None  # the activation timer's end (epoch ms); null: none


# --- client intents --------------------------------------------------------------------


class MoveIntent(ProtocolModel):
    type: Literal["move"]
    to: Pair  # the server picks the path it showed in `legal`


class AttackIntent(ProtocolModel):
    type: Literal["attack"]
    weapon: str
    target: int


class AbilityIntent(ProtocolModel):
    type: Literal["ability"]
    ability: str
    target_unit: int | None = None
    target_square: Pair | None = None


class WaitIntent(ProtocolModel):
    type: Literal["wait"]


class SkipIntent(ProtocolModel):
    type: Literal["skip"]


CombatIntent = MoveIntent | AttackIntent | AbilityIntent | WaitIntent | SkipIntent


class CombatIntentEnvelope(ProtocolModel):
    """Validates an intent coming from the client (discriminated by `type`)."""

    intent: CombatIntent = Field(discriminator="type")


# --- converters (pure) -----------------------------------------------------------------


def board_view(
    state: CombatState,
    factions: tuple[str, ...] = (),
    players: Sequence[PlayerView] | None = None,
) -> BoardView:
    board = state.board
    return BoardView(
        width=board.width,
        height=board.height,
        terrain=list(board.terrain),
        factions=list(factions) or None,
        players=list(players) if players is not None else None,
    )


def combat_view(combat_id: str, seq: int, state: CombatState) -> CombatView:
    active = state.active
    outcome = outcome_to_json(state.outcome)
    return CombatView(
        combat_id=combat_id,
        seq=seq,
        round=state.round,
        units=[
            UnitView(
                uid=u.uid,
                unit_type=u.unit_type,
                side=u.side,
                origin=u.origin,
                size=u.size,
                models=u.models,
                groups=[
                    GroupView(role=g.role, alive=g.alive, initial=g.initial, hp=g.hp)
                    for g in u.groups
                ],
                wounded=u.wounded,
                statuses=[
                    StatusView(
                        status=s.status, rounds_left=s.rounds_left, stacks=s.stacks
                    )
                    for s in u.statuses
                ],
                reactions=u.reactions,
            )
            for u in state.units
        ],
        overlays=[
            OverlayView(square=o.square, overlay=o.overlay, rounds_left=o.rounds_left)
            for o in state.overlays
        ],
        round_order=list(state.round_order),
        queue=list(state.queue),
        wait_queue=list(state.wait_queue),
        active=(
            ActiveView(
                uid=active.uid,
                movement_left=active.movement_left,
                ap_left=active.ap_left,
                weapons_used=list(active.weapons_used),
                moved=active.moved,
                attacked=active.attacked,
                movement_locked=active.movement_locked,
                acted=active.acted,
            )
            if active is not None
            else None
        ),
        outcome=OutcomeView(**outcome) if outcome is not None else None,
    )


def combat_legal(legal: LegalActions | None) -> CombatLegal | None:
    if legal is None:
        return None
    return CombatLegal(
        unit=legal.unit,
        moves=[
            MoveOptionView(to=m.destination, cost=m.cost, provokes=list(m.provokes))
            for m in legal.moves
        ],
        attacks=[
            AttackOptionView(
                weapon=a.weapon, target=a.target, ap_cost=a.ap_cost, cover=a.cover
            )
            for a in legal.attacks
        ],
        abilities=[
            AbilityOptionView(
                ability=a.ability,
                ap_cost=a.ap_cost,
                target_units=list(a.target_units),
                target_squares=list(a.target_squares),
            )
            for a in legal.abilities
        ],
        can_wait=legal.can_wait,
    )


def combat_event(seq: int, event: Event) -> CombatEvent:
    data = event_to_dict(event)
    kind = data.pop("type")
    return CombatEvent(seq=seq, type=kind, data=data)
