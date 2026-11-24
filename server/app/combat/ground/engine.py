"""Public API of the ground-combat engine. Pure: no I/O, no clock, explicit RNG.

    state, events = start_combat(ruleset, setup, rng)
    options = legal_actions(ruleset, state)
    state, events = apply_action(ruleset, state, action, rng)

The caller keeps one `random.Random` per combat and passes it to every call; a combat
is reproducible from `CombatRecord` (setup, seed, actions) via `replay`.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TypeVar

from app.combat.ground import events as ev
from app.combat.ground import hooks
from app.combat.ground import turn_order
from app.combat.ground.ability_use import check_ability, resolve_target, use_ability
from app.combat.ground.actions import Action, Attack, Move, Skip, UseAbility, Wait
from app.combat.ground.attack import check_attack, resolve_attack
from app.combat.ground.board import Square, footprint_distance
from app.combat.ground.movement import (
    MoveOption,
    execute_move,
    reachable,
    validate_path,
)
from app.combat.ground.resolver import IllegalAction, Resolver
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.setup import CombatSetup, SetupError, build_unit, validate_board
from app.combat.ground.state import CombatState, UnitId

# Bump when a rules or ability-function change alters fight outcomes (replays).
COMBAT_RULES_VERSION = 1

__all__ = [
    "COMBAT_RULES_VERSION",
    "AbilityOption",
    "AttackOption",
    "CombatRecord",
    "IllegalAction",
    "LegalActions",
    "MoveOption",
    "SetupError",
    "apply_action",
    "legal_actions",
    "replay",
    "start_combat",
]


@dataclass(frozen=True, slots=True)
class AttackOption:
    weapon: str
    target: UnitId
    ap_cost: int
    cover: bool  # the target would get cover (ranged only)


@dataclass(frozen=True, slots=True)
class AbilityOption:
    ability: str
    ap_cost: int
    target_units: tuple[UnitId, ...]
    target_squares: tuple[Square, ...]


@dataclass(frozen=True, slots=True)
class LegalActions:
    unit: UnitId
    moves: tuple[MoveOption, ...]
    attacks: tuple[AttackOption, ...]
    abilities: tuple[AbilityOption, ...]
    can_wait: bool
    can_skip: bool = True

    def any_besides_skip(self) -> bool:
        return bool(self.moves or self.attacks or self.abilities or self.can_wait)


@dataclass(frozen=True, slots=True)
class CombatRecord:
    """Everything needed to replay a combat exactly."""

    setup: CombatSetup
    seed: int
    content_hash: str
    rules_version: int
    actions: tuple[Action, ...]


# --- starting ----------------------------------------------------------------------------


def start_combat(
    ruleset: CombatRuleset,
    setup: CombatSetup,
    rng: random.Random,
    *,
    strict: bool = False,
) -> tuple[CombatState, list[ev.Event]]:
    validate_board(ruleset, setup.board)
    sides = sorted({u.side for u in setup.units})
    if len(sides) < 2:
        raise SetupError("a combat needs at least two sides")
    units = tuple(
        build_unit(ruleset, uid, u.unit_type, u.side, u.origin, u.models)
        for uid, u in enumerate(setup.units)
    )
    state = CombatState(board=setup.board, side_order=tuple(sides), units=units)
    res = Resolver(ruleset, state, rng, strict=strict)
    view = res.view
    taken: set[Square] = set()
    for unit in units:
        for square in unit.squares:
            if not view.props(square).passable or square in taken:
                raise SetupError(
                    f"unit {unit.uid} ({unit.unit_type}) can't be placed at {unit.origin}"
                )
            taken.add(square)

    order = list(sides)
    rng.shuffle(order)
    res.emit(
        ev.Rolled(
            "rules", "side_order", ",".join(map(str, sides)), tuple(order), order[0]
        )
    )
    res.state = replace(res.state, side_order=tuple(order))
    res.emit(
        ev.CombatStarted(
            tuple(order),
            tuple((u.uid, u.unit_type, u.side, u.origin, u.models) for u in units),
        )
    )
    res.dispatch(hooks.CombatStarted(res))
    turn_order.begin_round(res)
    _advance(res)
    return res.state, res.events


# --- legal actions -----------------------------------------------------------------------

T = TypeVar("T")


def _isolated(res: Resolver, base: CombatState, check: Callable[[], T]) -> T:
    """Run a check on the base state; whatever hooks did to the state is thrown away."""
    res.state = base
    res.events.clear()
    try:
        return check()
    finally:
        res.state = base
        res.events.clear()


def legal_actions(ruleset: CombatRuleset, state: CombatState) -> LegalActions | None:
    """What the active unit may do now (None when nobody is active or the fight is over)."""
    if state.outcome is not None or state.active is None:
        return None
    return _legal(Resolver(ruleset, state, random.Random(0), preview=True))


def _legal(res: Resolver) -> LegalActions:
    base = res.state
    active = base.active
    assert active is not None
    uid = active.uid
    unit = base.unit(uid)
    ruleset = res.ruleset

    moves: tuple[MoveOption, ...] = ()
    if not active.movement_locked and active.movement_left > 0:
        moves = tuple(reachable(res.view, uid, active.movement_left).values())

    enemies = [u.uid for u in base.living() if u.side != unit.side]
    attacks = []
    for weapon in unit.weapons():
        if weapon in active.weapons_used:
            continue
        definition = ruleset.weapon(weapon)
        for target in enemies:
            if (
                _isolated(res, base, lambda: check_attack(res, uid, weapon, target))
                is None
            ):
                cover = definition.mode == "ranged" and _isolated(
                    res, base, lambda: res.cover_for(uid, target)
                )
                attacks.append(AttackOption(weapon, target, definition.ap_cost, cover))

    abilities = []
    for bound in ruleset.unit_abilities[unit.unit_type]:
        definition = bound.definition
        if definition.kind != "active" or definition.targeting is None:
            continue
        aid, targeting = bound.ability_id, definition.targeting
        target_units: list[UnitId] = []
        target_squares: list[Square] = []
        if targeting.type == "square":
            x0, y0 = unit.origin
            r = targeting.range
            for y in range(y0 - r, y0 + unit.size + r):
                for x in range(x0 - r, x0 + unit.size + r):
                    if not base.board.in_bounds((x, y)):
                        continue
                    if (
                        _isolated(
                            res,
                            base,
                            lambda: check_ability(res, uid, aid, None, (x, y)),
                        )
                        is None
                    ):
                        target_squares.append((x, y))
        else:
            candidates = (
                [uid] if targeting.type == "self" else [u.uid for u in base.living()]
            )
            for target in candidates:
                if (
                    _isolated(
                        res, base, lambda: check_ability(res, uid, aid, target, None)
                    )
                    is None
                ):
                    target_units.append(target)
        if target_units or target_squares:
            abilities.append(
                AbilityOption(
                    aid, definition.ap_cost, tuple(target_units), tuple(target_squares)
                )
            )

    res.state = base
    return LegalActions(
        unit=uid,
        moves=moves,
        attacks=tuple(attacks),
        abilities=tuple(abilities),
        can_wait=turn_order.can_wait(res),
    )


# --- applying actions --------------------------------------------------------------------


def apply_action(
    ruleset: CombatRuleset,
    state: CombatState,
    action: Action,
    rng: random.Random,
    *,
    strict: bool = False,
) -> tuple[CombatState, list[ev.Event]]:
    """Apply the active unit's action. Raises `IllegalAction` (state and RNG unchanged)."""
    if state.outcome is not None:
        raise IllegalAction("combat.forbidden.over")
    if state.active is None:
        raise IllegalAction("combat.forbidden.no_active_unit")
    rng_state = rng.getstate()
    res = Resolver(ruleset, state, rng, strict=strict)
    uid = state.active.uid
    try:
        _perform(res, uid, action)
    except IllegalAction:
        rng.setstate(rng_state)
        raise
    _after_action(res)
    return res.state, res.events


def _perform(res: Resolver, uid: UnitId, action: Action) -> None:
    active = res.state.active
    assert active is not None
    if isinstance(action, Move):
        if active.movement_locked:
            raise IllegalAction("move.forbidden.after_attack")
        path = tuple(tuple(square) for square in action.path)
        reason = validate_path(res.view, uid, path, active.movement_left)  # type: ignore[arg-type]
        if reason is not None:
            raise IllegalAction(reason)
        execute_move(res, uid, path)  # type: ignore[arg-type]
    elif isinstance(action, Attack):
        if not 0 <= action.target < len(res.state.units):
            raise IllegalAction("attack.forbidden.target_dead")
        reason = check_attack(res, uid, action.weapon, action.target)
        if reason is not None:
            raise IllegalAction(reason)
        resolve_attack(res, uid, action.weapon, action.target)
    elif isinstance(action, UseAbility):
        square = (
            tuple(action.target_square) if action.target_square is not None else None
        )
        target = resolve_target(res, uid, action.ability, action.target_unit)
        reason = check_ability(res, uid, action.ability, target, square)  # type: ignore[arg-type]
        if reason is not None:
            raise IllegalAction(reason)
        use_ability(res, uid, action.ability, target, square)  # type: ignore[arg-type]
    elif isinstance(action, Wait):
        if not turn_order.can_wait(res):
            raise IllegalAction("wait.forbidden")
        turn_order.wait(res)
    elif isinstance(action, Skip):
        turn_order.end_activation(res)
    else:
        raise IllegalAction("combat.forbidden.unknown_action")


def _after_action(res: Resolver) -> None:
    if turn_order.check_annihilation(res):
        return
    active = res.state.active
    if active is not None:
        if (
            not res.state.unit(active.uid).alive
            or res.end_requested
            or not _has_options(res)
        ):
            turn_order.end_activation(res)
    _advance(res)


def _has_options(res: Resolver) -> bool:
    preview = Resolver(res.ruleset, res.state, random.Random(0), preview=True)
    return _legal(preview).any_besides_skip()


def _advance(res: Resolver) -> None:
    """Start activations until a unit has something to do, or the combat ends."""
    while res.state.outcome is None and res.state.active is None:
        if turn_order.check_annihilation(res):
            return
        uid = turn_order.next_unit(res)
        if uid is None:
            turn_order.end_round(res)
            if res.state.outcome is not None:
                return
            turn_order.begin_round(res)
            continue
        turn_order.begin_activation(res, uid)
        if turn_order.check_annihilation(res):
            return
        active = res.state.active
        if active is None:
            continue
        if not res.state.unit(uid).alive or res.end_requested or not _has_options(res):
            turn_order.end_activation(res)


# --- replay ------------------------------------------------------------------------------


def replay(
    ruleset: CombatRuleset, record: CombatRecord, *, strict: bool = False
) -> tuple[CombatState, list[ev.Event]]:
    """Rebuild a combat from its record. Raises if content or rules version differ."""
    if record.content_hash != ruleset.content_hash:
        raise ValueError("combat record was made with different content")
    if record.rules_version != COMBAT_RULES_VERSION:
        raise ValueError("combat record was made with a different rules version")
    rng = random.Random(record.seed)
    state, log = start_combat(ruleset, record.setup, rng, strict=strict)
    for action in record.actions:
        state, events = apply_action(ruleset, state, action, rng, strict=strict)
        log.extend(events)
    return state, log


def unit_distance(state: CombatState, a: UnitId, b: UnitId) -> int:
    ua, ub = state.unit(a), state.unit(b)
    return footprint_distance(ua.origin, ua.size, ub.origin, ub.size)
