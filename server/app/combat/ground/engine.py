"""Public API of the ground-combat engine. Pure: no I/O, no clock, explicit RNG.

    state, events = start_combat(ruleset, setup, rng)
    options = legal_actions(ruleset, state)
    state, events = apply_action(ruleset, state, action, rng)

The caller keeps one `random.Random` per combat and passes it to every call; a combat
is reproducible from `CombatRecord` (setup, seed, actions) via `replay`.
"""

import random
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.combat.ground import events as ev
from app.combat.ground import hooks
from app.combat.ground import turn_order
from app.combat.ground.ability_use import (
    check_ability,
    legal_targets,
    resolve_target,
    use_ability,
)
from app.combat.ground.actions import (
    Action,
    Attack,
    Concede,
    Move,
    Skip,
    UseAbility,
    Wait,
)
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
from app.combat.ground.setup import CombatSetup, SetupError, validate_setup
from app.combat.ground.state import CombatState, Outcome, UnitId

# Bump when a rules or ability-function change alters fight outcomes (replays).
COMBAT_RULES_VERSION = 2  # v2: redirected hits use the victim's armor and cover

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
    "resume",
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
    sides, units = validate_setup(ruleset, setup)
    state = CombatState(board=setup.board, side_order=sides, units=units)
    res = Resolver(ruleset, state, rng, strict=strict)

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

_LEGAL_CACHE_SIZE = 64
# Memo of `legal_actions` by state identity (states are immutable). The engine computes
# legal actions after every action anyway (to auto-end activations); the caller sending
# them to the client then gets the same result for free.
_legal_cache: "OrderedDict[int, tuple[CombatState, CombatRuleset, LegalActions]]" = (
    OrderedDict()
)


def legal_actions(ruleset: CombatRuleset, state: CombatState) -> LegalActions | None:
    """What the active unit may do now (None when nobody is active or the fight is over)."""
    if state.outcome is not None or state.active is None:
        return None
    hit = _legal_cache.get(id(state))
    if hit is not None and hit[0] is state and hit[1] is ruleset:
        _legal_cache.move_to_end(id(state))
        return hit[2]
    legal = _legal(Resolver(ruleset, state, random.Random(0), preview=True))
    _legal_cache[id(state)] = (state, ruleset, legal)
    if len(_legal_cache) > _LEGAL_CACHE_SIZE:
        _legal_cache.popitem(last=False)
    return legal


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
            with res.sandbox():
                legal = check_attack(res, uid, weapon, target) is None
                cover = (
                    legal and definition.mode == "ranged" and res.cover_for(uid, target)
                )
            if legal:
                attacks.append(AttackOption(weapon, target, definition.ap_cost, cover))

    abilities = []
    for bound in ruleset.unit_abilities[unit.unit_type]:
        if bound.definition.kind != "active":
            continue
        target_units, target_squares = legal_targets(res, uid, bound)
        if target_units or target_squares:
            abilities.append(
                AbilityOption(
                    bound.ability_id,
                    bound.definition.ap_cost,
                    tuple(target_units),
                    tuple(target_squares),
                )
            )

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
    """Apply the active unit's action (or a side's `Concede`). Raises `IllegalAction`
    (state and RNG unchanged)."""
    if state.outcome is not None:
        raise IllegalAction("combat.forbidden.over")
    if isinstance(action, Concede):
        return _concede(ruleset, state, action.side, rng)
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


def _concede(
    ruleset: CombatRuleset, state: CombatState, side: int, rng: random.Random
) -> tuple[CombatState, list[ev.Event]]:
    if side not in state.side_order:
        raise IllegalAction("concede.forbidden.side")
    res = Resolver(ruleset, state, rng)
    winners = tuple(sorted(s for s in state.side_order if s != side))
    turn_order.finish(res, Outcome(winners=winners, draw=False, reason="concede"))
    return res.state, res.events


def _require(reason: str | None) -> None:
    """Raise `IllegalAction` when a rules check returned a reason."""
    if reason is not None:
        raise IllegalAction(reason)


def _perform(res: Resolver, uid: UnitId, action: Action) -> None:
    active = res.state.active
    assert active is not None
    match action:
        case Move(path=path):
            if active.movement_locked:
                raise IllegalAction("move.forbidden.after_attack")
            squares = tuple((x, y) for x, y in path)  # JSON gives lists
            _require(validate_path(res.view, uid, squares, active.movement_left))
            execute_move(res, uid, squares)
        case Attack(weapon=weapon, target=target):
            if not 0 <= target < len(res.state.units):
                raise IllegalAction("attack.forbidden.target_dead")
            _require(check_attack(res, uid, weapon, target))
            resolve_attack(res, uid, weapon, target)
        case UseAbility(ability=ability, target_unit=unit, target_square=square):
            square = None if square is None else (square[0], square[1])
            unit = resolve_target(res, uid, ability, unit)
            _require(check_ability(res, uid, ability, unit, square))
            use_ability(res, uid, ability, unit, square)
        case Wait():
            if not turn_order.can_wait(res):
                raise IllegalAction("wait.forbidden")
            turn_order.wait(res)
        case Skip():
            turn_order.end_activation(res)
        case _:
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
    legal = legal_actions(res.ruleset, res.state)
    return legal is not None and legal.any_besides_skip()


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
    state, log, _ = resume(
        ruleset, record.setup, record.seed, record.actions, strict=strict
    )
    return state, log


def resume(
    ruleset: CombatRuleset,
    setup: CombatSetup,
    seed: int,
    actions: Sequence[Action],
    *,
    strict: bool = False,
) -> tuple[CombatState, list[ev.Event], random.Random]:
    """Rebuild a combat and hand back its RNG, positioned to continue the fight.
    Callers check content hash and rules version first (see `replay`)."""
    rng = random.Random(seed)
    state, log = start_combat(ruleset, setup, rng, strict=strict)
    for action in actions:
        state, events = apply_action(ruleset, state, action, rng, strict=strict)
        log.extend(events)
    return state, log, rng


def unit_distance(state: CombatState, a: UnitId, b: UnitId) -> int:
    ua, ub = state.unit(a), state.unit(b)
    return footprint_distance(ua.origin, ua.size, ub.origin, ub.size)
