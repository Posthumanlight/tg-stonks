"""Reusable conditions. `all_of` / `any_of` / `not` are built into the compiler."""

from pydantic import Field

from app.combat.ground.abilities.params import ArmorId, Params, StatName, TagId
from app.combat.ground.abilities.registry import condition
from app.combat.ground.hooks import HookContext, StatCalculating


class ArmorParam(Params):
    armor: ArmorId


class TagParam(Params):
    tag: TagId


class SquaresParam(Params):
    squares: int = Field(ge=0)


class StatParam(Params):
    stat: StatName


class PercentParam(Params):
    percent: int = Field(ge=0, le=100)


@condition("target_armor_is", params=ArmorParam)
def target_armor_is(ctx: HookContext, p: ArmorParam) -> bool:
    return ctx.target is not None and ctx.armor(ctx.target) == p.armor


@condition("target_has_tag", params=TagParam)
def target_has_tag(ctx: HookContext, p: TagParam) -> bool:
    return ctx.target is not None and ctx.has_tag(ctx.target, p.tag)


@condition("unit_has_tag", params=TagParam)
def unit_has_tag(ctx: HookContext, p: TagParam) -> bool:
    return ctx.unit is not None and ctx.has_tag(ctx.unit, p.tag)


@condition("owner_has_tag", params=TagParam)
def owner_has_tag(ctx: HookContext, p: TagParam) -> bool:
    return ctx.owner is not None and ctx.has_tag(ctx.owner, p.tag)


@condition("target_is_ally")
def target_is_ally(ctx: HookContext, p: Params) -> bool:
    """The event's target is on the owner's side (and is not the owner)."""
    return (
        ctx.target is not None
        and ctx.owner is not None
        and ctx.is_ally(ctx.owner, ctx.target)
    )


@condition("target_is_engaged")
def target_is_engaged(ctx: HookContext, p: Params) -> bool:
    return ctx.target is not None and ctx.is_engaged(ctx.target)


@condition("owner_has_moved")
def owner_has_moved(ctx: HookContext, p: Params) -> bool:
    return ctx.owner is not None and ctx.has_moved(ctx.owner)


@condition("owner_is_damaged")
def owner_is_damaged(ctx: HookContext, p: Params) -> bool:
    return ctx.owner is not None and ctx.hp_missing(ctx.owner) > 0


@condition("owner_sees_target")
def owner_sees_target(ctx: HookContext, p: Params) -> bool:
    return (
        ctx.owner is not None
        and ctx.target is not None
        and ctx.has_los(ctx.owner, ctx.target)
    )


@condition("target_within", params=SquaresParam)
def target_within(ctx: HookContext, p: SquaresParam) -> bool:
    return (
        ctx.owner is not None
        and ctx.target is not None
        and ctx.distance(ctx.owner, ctx.target) <= p.squares
    )


@condition("unit_within", params=SquaresParam)
def unit_within(ctx: HookContext, p: SquaresParam) -> bool:
    return (
        ctx.owner is not None
        and ctx.unit is not None
        and ctx.distance(ctx.owner, ctx.unit) <= p.squares
    )


@condition("stat_is", params=StatParam, events={"stat_calculating"})
def stat_is(ctx: StatCalculating, p: StatParam) -> bool:
    return ctx.stat == p.stat


@condition("chance", params=PercentParam)
def chance(ctx: HookContext, p: PercentParam) -> bool:
    return ctx.chance(p.percent)
