"""Reusable actions. Each one changes the combat only through `ctx`."""

from fractions import Fraction

from pydantic import Field

from app.combat.ground.abilities.params import (
    DiceParam,
    OverlayId,
    Params,
    StatusId,
    WeaponTypeId,
)
from app.combat.ground.abilities.registry import action
from app.combat.ground.hooks import (
    AbilityCast,
    AttackResolved,
    AttackValidating,
    DamageCalculating,
    HitAllocating,
    HitsCalculating,
    HookContext,
    LosChecking,
    OpportunityAttackTriggering,
    StatCalculating,
)


class PercentParam(Params):
    percent: int = Field(ge=0)


class AmountParam(Params):
    amount: int


class PositiveAmount(Params):
    amount: int = Field(ge=1)


class BoolParam(Params):
    value: bool


class ReasonParam(Params):
    reason_key: str


class SquaresParam(Params):
    squares: int = Field(ge=0)


class PerModelsParam(Params):
    per_models: int = Field(ge=1)


class StatusParam(Params):
    status: StatusId
    rounds: int = Field(ge=1)


class OverlayRadiusParam(Params):
    overlay: OverlayId
    radius: int = Field(ge=0)
    rounds: int = Field(ge=1)


class HitsInRadiusParam(Params):
    radius: int = Field(ge=0)
    hits_per_model: int = Field(ge=1)
    dice: DiceParam
    weapon_type: WeaponTypeId


class KeyParam(Params):
    key: str


# --- damage and hits -------------------------------------------------------------------


@action("multiply_damage", params=PercentParam, events={"damage_calculating"})
def multiply_damage(ctx: DamageCalculating, p: PercentParam) -> None:
    ctx.multiply_damage(Fraction(p.percent, 100))


@action("add_damage", params=AmountParam, events={"damage_calculating"})
def add_damage(ctx: DamageCalculating, p: AmountParam) -> None:
    ctx.add_damage(p.amount)


@action("set_cover", params=BoolParam, events={"damage_calculating", "los_checking"})
def set_cover(ctx: DamageCalculating | LosChecking, p: BoolParam) -> None:
    ctx.set_cover(p.value)


@action("add_hits", params=AmountParam, events={"hits_calculating"})
def add_hits(ctx: HitsCalculating, p: AmountParam) -> None:
    ctx.add_hits(p.amount)


@action(
    "add_hits_per_target_models", params=PerModelsParam, events={"hits_calculating"}
)
def add_hits_per_target_models(ctx: HitsCalculating, p: PerModelsParam) -> None:
    if ctx.target is not None:
        ctx.add_hits(ctx.models(ctx.target) // p.per_models)


@action("redirect_hit_to_owner", events={"hit_allocating"})
def redirect_hit_to_owner(ctx: HitAllocating, p: Params) -> None:
    if ctx.owner is not None and ctx.owner != ctx.target and ctx.is_alive(ctx.owner):
        ctx.redirect_hit(ctx.owner)


# --- attack validation / resolution ----------------------------------------------------


@action("forbid_attack", params=ReasonParam, events={"attack_validating"})
def forbid_attack(ctx: AttackValidating, p: ReasonParam) -> None:
    ctx.forbid_attack(p.reason_key)


@action("allow_without_los", events={"attack_validating"})
def allow_without_los(ctx: AttackValidating, p: Params) -> None:
    ctx.allow_without_los()


@action("add_range", params=SquaresParam, events={"attack_validating"})
def add_range(ctx: AttackValidating, p: SquaresParam) -> None:
    ctx.add_range(p.squares)


@action("keep_movement", events={"attack_resolved"})
def keep_movement(ctx: AttackResolved, p: Params) -> None:
    ctx.keep_movement()


@action("cancel_opportunity_attack", events={"opportunity_attack_triggering"})
def cancel_opportunity_attack(ctx: OpportunityAttackTriggering, p: Params) -> None:
    ctx.cancel_opportunity_attack()


# --- stats, statuses, healing ----------------------------------------------------------


@action("add_stat", params=AmountParam, events={"stat_calculating"})
def add_stat(ctx: StatCalculating, p: AmountParam) -> None:
    ctx.add_stat(p.amount)


@action("heal_owner", params=PositiveAmount)
def heal_owner(ctx: HookContext, p: PositiveAmount) -> None:
    if ctx.owner is not None:
        ctx.heal(ctx.owner, p.amount)


@action("apply_status_to_owner", params=StatusParam)
def apply_status_to_owner(ctx: HookContext, p: StatusParam) -> None:
    if ctx.owner is not None:
        ctx.apply_status(ctx.owner, p.status, p.rounds)


@action("apply_status_to_target", params=StatusParam)
def apply_status_to_target(ctx: HookContext, p: StatusParam) -> None:
    if ctx.target is not None and ctx.is_alive(ctx.target):
        ctx.apply_status(ctx.target, p.status, p.rounds)


@action("set_owner_reactions", params=AmountParam)
def set_owner_reactions(ctx: HookContext, p: AmountParam) -> None:
    if ctx.owner is not None:
        ctx.set_reactions(ctx.owner, p.amount)


@action("log_message", params=KeyParam)
def log_message(ctx: HookContext, p: KeyParam) -> None:
    ctx.log_message(p.key)


# --- area effects (active abilities) ---------------------------------------------------


@action("place_overlay_in_radius", params=OverlayRadiusParam, events={"ability_cast"})
def place_overlay_in_radius(ctx: AbilityCast, p: OverlayRadiusParam) -> None:
    if ctx.cast_square is None:
        return
    for square in ctx.squares_in_radius(ctx.cast_square, p.radius):
        ctx.place_overlay(square, p.overlay, p.rounds)


@action("deal_hits_in_radius", params=HitsInRadiusParam, events={"ability_cast"})
def deal_hits_in_radius(ctx: AbilityCast, p: HitsInRadiusParam) -> None:
    if ctx.cast_square is None or ctx.owner is None:
        return
    for unit in ctx.units_in_range(ctx.cast_square, p.radius):  # ordered by unit id
        ctx.deal_hits(
            ctx.owner,
            unit,
            ctx.models(unit) * p.hits_per_model,
            p.dice,
            p.weapon_type,
            ranged=True,
        )
