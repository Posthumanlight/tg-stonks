"""Active abilities: targeting checks and casting (docs/combat-ground.md "Abilities")."""

from typing import TYPE_CHECKING

from app.combat.ground import events as ev
from app.combat.ground import hooks
from app.combat.ground.board import Square, footprint_distance
from app.combat.ground.los import sight_to_square
from app.combat.ground.state import UnitId

if TYPE_CHECKING:
    from app.combat.ground.resolver import Resolver


def resolve_target(
    res: "Resolver", uid: UnitId, ability_id: str, target_unit: UnitId | None
) -> UnitId | None:
    """Self-targeted abilities target the caster even when no target is given."""
    bound = res.ruleset.active_ability(res.state.unit(uid).unit_type, ability_id)
    if bound is not None and bound.definition.targeting.type == "self":  # type: ignore[union-attr]
        return uid if target_unit is None else target_unit
    return target_unit


def check_ability(
    res: "Resolver",
    uid: UnitId,
    ability_id: str,
    target_unit: UnitId | None,
    target_square: Square | None,
) -> str | None:
    """None if the cast is legal, else the reason (an i18n key)."""
    state = res.state
    active = state.active
    if active is None or active.uid != uid:
        return "ability.forbidden.not_active"
    unit = state.unit(uid)
    bound = res.ruleset.active_ability(unit.unit_type, ability_id)
    if bound is None:
        return "ability.forbidden.unknown"
    definition = bound.definition
    targeting = definition.targeting
    assert targeting is not None
    if active.ap_left < definition.ap_cost:
        return "ability.forbidden.not_enough_ap"
    if unit.cooldown(ability_id) > 0:
        return "ability.forbidden.on_cooldown"
    if definition.uses is not None and unit.used(ability_id) >= definition.uses:
        return "ability.forbidden.no_uses"

    if targeting.type == "self":
        if target_unit != uid or target_square is not None:
            return "ability.forbidden.bad_target"
    elif targeting.type == "square":
        if target_square is None or target_unit is not None:
            return "ability.forbidden.bad_target"
        if not state.board.in_bounds(target_square):
            return "ability.forbidden.bad_target"
        distance = footprint_distance(unit.origin, unit.size, target_square, 1)
        if distance > targeting.range:
            return "ability.forbidden.out_of_range"
        if targeting.los and not sight_to_square(res.view, uid, target_square):
            return "ability.forbidden.no_los"
    else:
        if target_unit is None or target_square is not None:
            return "ability.forbidden.bad_target"
        if not 0 <= target_unit < len(state.units) or not state.unit(target_unit).alive:
            return "ability.forbidden.bad_target"
        target = state.unit(target_unit)
        if targeting.type == "ally" and target.side != unit.side:
            return "ability.forbidden.bad_target"
        if targeting.type == "enemy" and target.side == unit.side:
            return "ability.forbidden.bad_target"
        distance = footprint_distance(
            unit.origin, unit.size, target.origin, target.size
        )
        if distance > targeting.range:
            return "ability.forbidden.out_of_range"
        if targeting.los and target_unit != uid and not res.sight(uid, target_unit).los:
            return "ability.forbidden.no_los"

    ctx = hooks.AbilityCasting(
        res,
        unit=uid,
        ability=ability_id,
        cast_unit=target_unit,
        cast_square=target_square,
    )
    res.dispatch(ctx)
    return ctx.forbidden


def use_ability(
    res: "Resolver",
    uid: UnitId,
    ability_id: str,
    target_unit: UnitId | None,
    target_square: Square | None,
) -> None:
    """Cast an already-validated ability: pay, run `on_cast`, then `ability_cast` hooks."""
    unit = res.state.unit(uid)
    bound = res.ruleset.active_ability(unit.unit_type, ability_id)
    assert bound is not None and res.state.active is not None
    definition = bound.definition
    active = res.state.active
    res.update_active(ap_left=active.ap_left - definition.ap_cost, acted=True)
    cooldowns = dict(unit.cooldowns)
    if definition.cooldown > 0:
        cooldowns[ability_id] = definition.cooldown
    uses = dict(unit.uses)
    uses[ability_id] = uses.get(ability_id, 0) + 1
    res.update_unit(
        uid,
        cooldowns=tuple(sorted(cooldowns.items())),
        uses=tuple(sorted(uses.items())),
    )
    res.emit(ev.AbilityUsed(uid, ability_id, target_unit, target_square))
    ctx = hooks.AbilityCast(
        res,
        unit=uid,
        ability=ability_id,
        cast_unit=target_unit,
        cast_square=target_square,
    )
    res.run_trigger((), bound.on_cast, ctx, uid, ability_id)
    res.dispatch(ctx)
