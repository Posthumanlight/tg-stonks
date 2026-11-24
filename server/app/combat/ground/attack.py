"""The attack pipeline (docs/combat-ground.md "Attack resolution").

validate → declare (spend AP) → hits → per hit: damage → stochastic rounding →
allocation → resolve. Every step raises its hook event.
"""

from fractions import Fraction
from typing import TYPE_CHECKING

from app.combat.ground import events as ev
from app.combat.ground import hooks
from app.combat.ground.board import footprint_distance
from app.combat.ground.dice import Dice
from app.combat.ground.state import UnitId

if TYPE_CHECKING:
    from app.combat.ground.resolver import Resolver


def check_attack(
    res: "Resolver",
    attacker: UnitId,
    weapon_id: str,
    target: UnitId,
    *,
    opportunity: bool = False,
    free: bool = False,
) -> str | None:
    """None if the attack is legal, else the reason (an i18n key)."""
    state, ruleset = res.state, res.ruleset
    a, t = state.unit(attacker), state.unit(target)
    if not t.alive:
        return "attack.forbidden.target_dead"
    if a.side == t.side:
        return "attack.forbidden.friendly"
    if not a.alive or weapon_id not in a.weapons():
        return "attack.forbidden.no_carrier"
    weapon = ruleset.weapon(weapon_id)
    if not opportunity and not free:
        active = state.active
        if active is None or active.uid != attacker:
            return "attack.forbidden.not_active"
        if weapon_id in active.weapons_used:
            return "attack.forbidden.weapon_used"
        if active.ap_left < weapon.ap_cost:
            return "attack.forbidden.not_enough_ap"
        if ruleset.rules.first_round_no_attacks and state.round == 1:
            return "attack.forbidden.first_round"
    distance = footprint_distance(a.origin, a.size, t.origin, t.size)
    ctx = hooks.AttackValidating(
        res,
        unit=attacker,
        target=target,
        weapon=weapon_id,
        distance=distance,
        opportunity=opportunity,
    )
    res.dispatch(ctx)
    if ctx.forbidden is not None:
        return ctx.forbidden
    low, high = weapon.range
    if not low <= distance <= high + ctx.range_bonus:
        return "attack.forbidden.out_of_range"
    needs_los = weapon.mode == "ranged" or distance > 1
    if needs_los and not ctx.without_los and not res.sight(attacker, target).los:
        return "attack.forbidden.no_los"
    return None


def resolve_attack(
    res: "Resolver",
    attacker: UnitId,
    weapon_id: str,
    target: UnitId,
    *,
    opportunity: bool = False,
    free: bool = False,
) -> tuple[int, int]:
    """Resolve an already-validated attack. Returns (total damage, models killed)."""
    weapon = res.ruleset.weapon(weapon_id)
    carriers = res.state.unit(attacker).carriers(weapon_id)
    source = f"weapon:{weapon_id}"
    ap_cost = 0
    if not opportunity and not free:
        declared = hooks.AttackDeclared(
            res, unit=attacker, target=target, weapon=weapon_id, ap_cost=weapon.ap_cost
        )
        res.dispatch(declared)
        active = res.state.active
        assert active is not None
        ap_cost = min(declared.ap_cost, active.ap_left)
        res.update_active(
            ap_left=active.ap_left - ap_cost,
            weapons_used=active.weapons_used + (weapon_id,),
            attacked=True,
            movement_locked=True,
            acted=True,
        )
    res.emit(ev.AttackDeclared(attacker, target, weapon_id, opportunity, ap_cost))

    hits = Fraction(weapon.hits * carriers)
    if opportunity:
        hits *= Fraction(res.ruleset.rules.opportunity_attack_hit_percent, 100)
    hits_ctx = hooks.HitsCalculating(
        res, unit=attacker, target=target, weapon=weapon_id, hits=hits
    )
    res.dispatch(hits_ctx)
    n_hits = res.round_value(max(hits_ctx.hits, Fraction(0)), source)

    ranged = weapon.mode == "ranged"
    cover = ranged and res.cover_for(attacker, target)
    total, kills = resolve_hits(
        res,
        attacker,
        target,
        n_hits,
        weapon.damage,
        weapon.type,
        ranged,
        cover=cover,
        weapon=weapon_id,
    )

    resolved = hooks.AttackResolved(
        res,
        unit=attacker,
        target=target,
        weapon=weapon_id,
        total_damage=total,
        kills=kills,
    )
    res.dispatch(resolved)
    active = res.state.active
    if (
        resolved.keep
        and not opportunity
        and not free
        and active
        and active.uid == attacker
    ):
        res.update_active(movement_locked=False)
    res.emit(ev.AttackResolved(attacker, target, weapon_id, n_hits, total, kills))
    return total, kills


def resolve_hits(
    res: "Resolver",
    source: UnitId,
    target: UnitId,
    n_hits: int,
    dice: Dice,
    weapon_type: str,
    ranged: bool,
    *,
    cover: bool,
    weapon: str | None,
) -> tuple[int, int]:
    """Roll and allocate hits one by one. Returns (total damage applied, models killed)."""
    table = res.ruleset.content.damage_table[weapon_type]
    tag = f"weapon:{weapon}" if weapon else f"hits:{weapon_type}"
    total = kills = 0
    for index in range(n_hits):
        if not res.state.unit(target).alive:
            break  # remaining hits are lost
        roll = res.roll(dice, tag)
        damage_ctx = hooks.DamageCalculating(
            res,
            unit=source,
            target=target,
            weapon=weapon,
            weapon_type=weapon_type,
            ranged=ranged,
            roll=roll,
            cover=cover,
            armor_percent=table[res.unit_def(target).armor],
        )
        res.dispatch(damage_ctx)
        value = Fraction(damage_ctx.roll + damage_ctx.flat) * Fraction(
            damage_ctx.armor_percent, 100
        )
        in_cover = ranged and damage_ctx.cover
        if in_cover:
            value /= 2
        for factor in damage_ctx.multipliers:
            value *= factor
        damage = res.round_value(max(value, Fraction(0)), tag)

        allocating = hooks.HitAllocating(
            res, unit=source, target=target, weapon=weapon, damage=damage
        )
        res.dispatch(allocating)
        if allocating.prevented:
            res.emit(ev.HitPrevented(source, target, index))
            continue
        victim = target
        if (
            allocating.redirect is not None
            and res.state.unit(allocating.redirect).alive
        ):
            victim = allocating.redirect
        applied, killed = res.apply_damage(
            victim, damage, source=source, weapon=weapon, index=index, cover=in_cover
        )
        total += applied
        kills += killed is not None
    return total, kills
