"""Active abilities: targeting checks and casting (docs/combat-ground.md "Abilities")."""

import operator
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.combat.ground import events as ev
from app.combat.ground import hooks
from app.combat.ground.board import Square, footprint_distance
from app.combat.ground.los import sight_to_square
from app.combat.ground.state import UnitId

if TYPE_CHECKING:
    from app.combat.ground.resolver import Resolver
    from app.combat.ground.ruleset import BoundAbility

_forbidden = "ability.forbidden.{}".format  # reasons are i18n keys

# Which (caster side, target side) pairs each unit-targeting type accepts.
_SIDES_OK: dict[str, Callable[[int, int], bool]] = {
    "ally": operator.eq,
    "enemy": operator.ne,
    "unit": lambda _caster, _target: True,
}

# Where a target is (footprint origin and size) and how to test LoS to it.
TargetSpot = tuple[Square, int, Callable[[], bool]]


def _bound(res: "Resolver", uid: UnitId, ability_id: str) -> "BoundAbility | None":
    return res.ruleset.active_ability(res.state.unit(uid).unit_type, ability_id)


def _cast_args(
    uid: UnitId,
    ability_id: str,
    target_unit: UnitId | None,
    target_square: Square | None,
) -> dict[str, Any]:
    """Shared fields of the `ability_casting` / `ability_cast` hook contexts."""
    return {
        "unit": uid,
        "ability": ability_id,
        "cast_unit": target_unit,
        "cast_square": target_square,
    }


def resolve_target(
    res: "Resolver", uid: UnitId, ability_id: str, target_unit: UnitId | None
) -> UnitId | None:
    """Self-targeted abilities target the caster even when no target is given."""
    bound = _bound(res, uid, ability_id)
    targeting = bound.definition.targeting if bound is not None else None
    if target_unit is None and targeting is not None and targeting.type == "self":
        return uid
    return target_unit


def _payment_problem(res: "Resolver", uid: UnitId, bound: "BoundAbility") -> str | None:
    """AP, cooldown and uses; the first failing check's reason, or None."""
    definition, unit, active = bound.definition, res.state.unit(uid), res.state.active
    assert active is not None
    checks = (
        (active.ap_left < definition.ap_cost, "not_enough_ap"),
        (unit.cooldown(bound.ability_id) > 0, "on_cooldown"),
        (
            definition.uses is not None
            and unit.used(bound.ability_id) >= definition.uses,
            "no_uses",
        ),
    )
    return next((reason for failed, reason in checks if failed), None)


def _locate_target(
    res: "Resolver",
    uid: UnitId,
    kind: str,
    target_unit: UnitId | None,
    target_square: Square | None,
) -> TargetSpot | None:
    """The target's spot, or None if the given target doesn't fit the targeting type."""
    state = res.state
    match kind, target_unit, target_square:
        case "self", int() as tid, None if tid == uid:
            caster = state.unit(uid)
            return caster.origin, caster.size, lambda: True
        case "square", None, (int(), int()) as square if state.board.in_bounds(square):
            return square, 1, lambda: sight_to_square(res.view, uid, square)
        case ("ally" | "enemy" | "unit"), int() as tid, None if (
            0 <= tid < len(state.units)
            and state.unit(tid).alive
            and _SIDES_OK[kind](state.unit(uid).side, state.unit(tid).side)
        ):
            target = state.unit(tid)
            return (
                target.origin,
                target.size,
                lambda: tid == uid or res.sight(uid, tid).los,
            )
    return None


def _target_problem(
    res: "Resolver",
    uid: UnitId,
    bound: "BoundAbility",
    target_unit: UnitId | None,
    target_square: Square | None,
) -> str | None:
    """Target shape, range and LoS — the pure part of targeting."""
    targeting = bound.definition.targeting
    assert targeting is not None
    spot = _locate_target(res, uid, targeting.type, target_unit, target_square)
    if spot is None:
        return "bad_target"
    origin, size, sees = spot
    caster = res.state.unit(uid)
    if footprint_distance(caster.origin, caster.size, origin, size) > targeting.range:
        return "out_of_range"
    if targeting.los and not sees():
        return "no_los"
    return None


def _casting_hooks_allow(
    res: "Resolver",
    uid: UnitId,
    ability_id: str,
    target_unit: UnitId | None,
    target_square: Square | None,
) -> str | None:
    """`ability_casting` hooks: None, or the reason a hook forbade the cast."""
    ctx = hooks.AbilityCasting(
        res, **_cast_args(uid, ability_id, target_unit, target_square)
    )
    res.dispatch(ctx)
    return ctx.forbidden


def check_ability(
    res: "Resolver",
    uid: UnitId,
    ability_id: str,
    target_unit: UnitId | None,
    target_square: Square | None,
) -> str | None:
    """None if the cast is legal, else the reason (an i18n key)."""
    active = res.state.active
    if active is None or active.uid != uid:
        return _forbidden("not_active")
    bound = _bound(res, uid, ability_id)
    if bound is None or bound.definition.targeting is None:
        return _forbidden("unknown")
    problem = _payment_problem(res, uid, bound) or _target_problem(
        res, uid, bound, target_unit, target_square
    )
    if problem is not None:
        return _forbidden(problem)
    return _casting_hooks_allow(res, uid, ability_id, target_unit, target_square)


def legal_targets(
    res: "Resolver", uid: UnitId, bound: "BoundAbility"
) -> tuple[list[UnitId], list[Square]]:
    """Every valid target of an active ability, for the legal-actions preview.

    Same rules as `check_ability`, enumerated in bulk: payment is checked once, and
    the `ability_casting` hooks only run (in a sandbox) when some ability listens.
    """
    targeting = bound.definition.targeting
    active = res.state.active
    if targeting is None or active is None or active.uid != uid:
        return [], []
    if _payment_problem(res, uid, bound) is not None:
        return [], []
    hooked = bool(res.ruleset.listeners_for(hooks.AbilityCasting.event))

    def allowed(target_unit: UnitId | None, target_square: Square | None) -> bool:
        if _target_problem(res, uid, bound, target_unit, target_square) is not None:
            return False
        if not hooked:
            return True
        with res.sandbox():
            return (
                _casting_hooks_allow(
                    res, uid, bound.ability_id, target_unit, target_square
                )
                is None
            )

    state = res.state
    if targeting.type == "square":
        unit = state.unit(uid)
        x0, y0, reach = unit.origin[0], unit.origin[1], targeting.range
        squares = [
            (x, y)
            for y in range(y0 - reach, y0 + unit.size + reach)
            for x in range(x0 - reach, x0 + unit.size + reach)
            if state.board.in_bounds((x, y)) and allowed(None, (x, y))
        ]
        return [], squares
    candidates = [uid] if targeting.type == "self" else [u.uid for u in state.living()]
    return [t for t in candidates if allowed(t, None)], []


def _with_entry(
    pairs: tuple[tuple[str, int], ...], key: str, value: int
) -> tuple[tuple[str, int], ...]:
    return tuple(sorted({**dict(pairs), key: value}.items()))


def use_ability(
    res: "Resolver",
    uid: UnitId,
    ability_id: str,
    target_unit: UnitId | None,
    target_square: Square | None,
) -> None:
    """Cast an already-validated ability: pay, run `on_cast`, then `ability_cast` hooks."""
    bound = _bound(res, uid, ability_id)
    active = res.state.active
    assert bound is not None and active is not None
    definition, unit = bound.definition, res.state.unit(uid)

    res.update_active(ap_left=active.ap_left - definition.ap_cost, acted=True)
    res.update_unit(
        uid,
        cooldowns=(
            _with_entry(unit.cooldowns, ability_id, definition.cooldown)
            if definition.cooldown > 0
            else unit.cooldowns
        ),
        uses=_with_entry(unit.uses, ability_id, unit.used(ability_id) + 1),
    )
    res.emit(ev.AbilityUsed(uid, ability_id, target_unit, target_square))

    ctx = hooks.AbilityCast(
        res, **_cast_args(uid, ability_id, target_unit, target_square)
    )
    res.run_trigger((), bound.on_cast, ctx, uid, ability_id)
    res.dispatch(ctx)
