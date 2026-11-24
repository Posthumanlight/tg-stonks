"""Hook events and their contexts: the *only* interface ability functions get.

The core rules raise a hook event at every decision point (docs/combat-ground.md
"Event catalogue"). Each event has a context class: shared queries/effects on
`HookContext`, plus that event's fields and mutators. Ability functions read and change
the combat exclusively through `ctx`.
"""

from fractions import Fraction
from typing import TYPE_CHECKING, Any, ClassVar

from app.combat.ground.board import Square, footprint_distance
from app.combat.ground.dice import Dice

if TYPE_CHECKING:
    from app.combat.ground.resolver import Resolver

UnitId = int


class HookContext:
    event: ClassVar[str] = ""
    _mutable: ClassVar[
        tuple[str, ...]
    ] = ()  # fields restored when a trigger rolls back

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId | None = None,
        target: UnitId | None = None,
        weapon: str | None = None,
    ) -> None:
        self._res = res
        self.unit = unit  # the event's subject
        self.target = target
        self.weapon = weapon
        self.owner: UnitId | None = None  # holder of the ability whose trigger runs
        self.source: str = ""  # id of the ability whose trigger runs (roll logging)

    @property
    def wielder(self) -> UnitId | None:
        """The unit using `weapon` in this event (weapon-scoped triggers belong to it)."""
        return self.unit

    # --- rollback support (used by the dispatcher) ------------------------------------

    def _snapshot(self) -> tuple[Any, ...]:
        return tuple(
            list(v) if isinstance(v := getattr(self, n), list) else v
            for n in self._mutable
        )

    def _restore(self, snapshot: tuple[Any, ...]) -> None:
        for name, value in zip(self._mutable, snapshot):
            setattr(self, name, value)

    # --- queries ----------------------------------------------------------------------

    @property
    def round(self) -> int:
        return self._res.state.round

    def is_alive(self, u: UnitId) -> bool:
        return self._res.state.unit(u).alive

    def unit_type(self, u: UnitId) -> str:
        return self._res.state.unit(u).unit_type

    def side(self, u: UnitId) -> int:
        return self._res.state.unit(u).side

    def has_tag(self, u: UnitId, tag: str) -> bool:
        return tag in self._res.unit_def(u).tags

    def armor(self, u: UnitId) -> str:
        return self._res.unit_def(u).armor

    def is_enemy(self, a: UnitId, b: UnitId) -> bool:
        return self.side(a) != self.side(b)

    def is_ally(self, a: UnitId, b: UnitId) -> bool:
        """Same side, different unit."""
        return a != b and self.side(a) == self.side(b)

    def models(self, u: UnitId) -> int:
        return self._res.state.unit(u).models

    def max_models(self, u: UnitId) -> int:
        return self._res.state.unit(u).initial_models

    def hp(self, u: UnitId) -> int:
        return self._res.total_hp(u)

    def hp_missing(self, u: UnitId) -> int:
        """Damage on the wounded model (0 when no model is wounded)."""
        unit = self._res.state.unit(u)
        if unit.wounded is None:
            return 0
        group, hp_left = unit.wounded
        return unit.groups[group].hp - hp_left

    def stat(self, u: UnitId, stat: str) -> int:
        return self._res.base_stat(u, stat)

    def has_status(self, u: UnitId, status: str) -> bool:
        return self._res.state.unit(u).has_status(status)

    def status_stacks(self, u: UnitId, status: str) -> int:
        return sum(
            s.stacks for s in self._res.state.unit(u).statuses if s.status == status
        )

    def is_engaged(self, u: UnitId) -> bool:
        return self._res.is_engaged(u)

    def has_moved(self, u: UnitId) -> bool:
        active = self._res.state.active
        return active is not None and active.uid == u and active.moved

    def has_attacked(self, u: UnitId) -> bool:
        active = self._res.state.active
        return active is not None and active.uid == u and active.attacked

    def distance(self, a: UnitId, b: UnitId) -> int:
        ua, ub = self._res.state.unit(a), self._res.state.unit(b)
        return footprint_distance(ua.origin, ua.size, ub.origin, ub.size)

    def square_of(self, u: UnitId) -> Square:
        return self._res.state.unit(u).origin

    def has_los(self, a: UnitId, b: UnitId) -> bool:
        return self._res.sight(a, b).los

    def in_cover(self, target: UnitId, attacker: UnitId) -> bool:
        return self._res.sight(attacker, target).cover

    def ap_left(self, u: UnitId) -> int:
        active = self._res.state.active
        return active.ap_left if active is not None and active.uid == u else 0

    def movement_left(self, u: UnitId) -> int:
        active = self._res.state.active
        return active.movement_left if active is not None and active.uid == u else 0

    def units_in_range(self, square: Square, radius: int) -> list[UnitId]:
        return [
            u.uid
            for u in self._res.state.living()
            if footprint_distance(square, 1, u.origin, u.size) <= radius
        ]

    def enemies_in_range(self, u: UnitId, radius: int) -> list[UnitId]:
        return [v for v in self._units_near(u, radius) if self.is_enemy(u, v)]

    def allies_in_range(self, u: UnitId, radius: int) -> list[UnitId]:
        return [v for v in self._units_near(u, radius) if self.is_ally(u, v)]

    def units_in_los(self, u: UnitId) -> list[UnitId]:
        return [
            v.uid
            for v in self._res.state.living()
            if v.uid != u and self.has_los(u, v.uid)
        ]

    def squares_in_radius(self, square: Square, radius: int) -> list[Square]:
        board = self._res.state.board
        x0, y0 = square
        return [
            (x, y)
            for y in range(y0 - radius, y0 + radius + 1)
            for x in range(x0 - radius, x0 + radius + 1)
            if board.in_bounds((x, y))
        ]

    def terrain(self, square: Square) -> str:
        return self._res.state.board.terrain_at(square)

    def is_passable(self, square: Square) -> bool:
        return self._res.view.props(square).passable

    def unit_at(self, square: Square) -> UnitId | None:
        return self._res.view.occupant(square)

    def _units_near(self, u: UnitId, radius: int) -> list[UnitId]:
        return [
            v.uid
            for v in self._res.state.living()
            if v.uid != u and self.distance(u, v.uid) <= radius
        ]

    # --- randomness (logged) ----------------------------------------------------------

    def roll(self, dice: Dice | str | int) -> int:
        return self._res.roll(Dice.parse(dice), self.source)

    def chance(self, percent: int) -> bool:
        return self._res.chance(percent, self.source)

    # --- effects (each raises its own events) ------------------------------------------

    def deal_hits(
        self,
        source: UnitId,
        target: UnitId,
        hits: int,
        dice: Dice | str | int,
        weapon_type: str,
        ranged: bool,
    ) -> int:
        return self._res.deal_hits(
            source, target, hits, Dice.parse(dice), weapon_type, ranged
        )

    def deal_true_damage(
        self, target: UnitId, amount: int, source: UnitId | None = None
    ) -> int:
        return self._res.apply_damage(target, amount, source=source, weapon=None)[0]

    def free_attack(self, source: UnitId, target: UnitId, weapon: str) -> None:
        self._res.free_attack(source, target, weapon)

    def heal(self, u: UnitId, amount: int) -> int:
        return self._res.heal(u, amount)

    def revive_models(self, u: UnitId, count: int) -> int:
        return self._res.revive_models(u, count)

    def apply_status(self, u: UnitId, status: str, rounds: int) -> None:
        self._res.apply_status(u, status, rounds)

    def remove_status(self, u: UnitId, status: str) -> None:
        self._res.remove_status(u, status)

    def grant_ap(self, u: UnitId, amount: int) -> None:
        self._res.grant(u, ap=amount)

    def grant_movement(self, u: UnitId, amount: int) -> None:
        self._res.grant(u, movement=amount)

    def set_reactions(self, u: UnitId, amount: int) -> None:
        self._res.set_reactions(u, amount)

    def end_activation(self, u: UnitId) -> None:
        self._res.request_end_activation(u)

    def push(self, u: UnitId, away_from: Square, squares: int) -> None:
        self._res.push(u, away_from, squares)

    def teleport(self, u: UnitId, square: Square) -> bool:
        return self._res.teleport(u, square)

    def spawn_unit(
        self, unit_type: str, side_of: UnitId, square: Square, models: int | None = None
    ) -> UnitId | None:
        return self._res.spawn_unit(unit_type, self.side(side_of), square, models)

    def place_overlay(self, square: Square, overlay: str, rounds: int) -> None:
        self._res.place_overlay(square, overlay, rounds)

    def remove_overlay(self, square: Square, overlay: str) -> None:
        self._res.remove_overlay(square, overlay)

    def log_message(self, key: str, **params: Any) -> None:
        self._res.log_message(key, params)


# --- per-event contexts -----------------------------------------------------------------


class CombatStarted(HookContext):
    event = "combat_started"


class RoundStarted(HookContext):
    event = "round_started"


class RoundEnded(HookContext):
    event = "round_ended"


class ActivationStarted(HookContext):
    event = "activation_started"


class ActivationEnded(HookContext):
    event = "activation_ended"


class UnitWaited(HookContext):
    event = "unit_waited"


class StatCalculating(HookContext):
    event = "stat_calculating"
    _mutable = ("bonus", "multipliers")

    def __init__(self, res: "Resolver", *, unit: UnitId, stat: str, value: int) -> None:
        super().__init__(res, unit=unit)
        self.stat = stat
        self.value = value
        self.bonus = 0
        self.multipliers: list[Fraction] = []

    def add_stat(self, amount: int) -> None:
        self.bonus += amount

    def multiply_stat(self, factor: Fraction) -> None:
        self.multipliers.append(Fraction(factor))


class StepMoving(HookContext):
    event = "step_moving"
    _mutable = ("cost", "cancelled")

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        from_square: Square,
        to_square: Square,
        cost: int,
    ) -> None:
        super().__init__(res, unit=unit)
        self.from_square = from_square
        self.to_square = to_square
        self.cost = cost
        self.cancelled = False

    def cancel_step(self) -> None:
        self.cancelled = True

    def set_step_cost(self, cost: int) -> None:
        self.cost = max(0, cost)


class StepMoved(HookContext):
    event = "step_moved"

    def __init__(
        self, res: "Resolver", *, unit: UnitId, from_square: Square, to_square: Square
    ) -> None:
        super().__init__(res, unit=unit)
        self.from_square = from_square
        self.to_square = to_square


class OpportunityAttackTriggering(HookContext):
    """Subject: the reacting enemy; target: the unit leaving its reach."""

    event = "opportunity_attack_triggering"
    _mutable = ("cancelled", "weapon")

    def __init__(
        self, res: "Resolver", *, unit: UnitId, target: UnitId, weapon: str
    ) -> None:
        super().__init__(res, unit=unit, target=target, weapon=weapon)
        self.cancelled = False

    def cancel_opportunity_attack(self) -> None:
        self.cancelled = True

    def set_opportunity_weapon(self, weapon: str) -> None:
        self.weapon = weapon


class AttackValidating(HookContext):
    event = "attack_validating"
    _mutable = ("without_los", "range_bonus", "forbidden")

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        target: UnitId,
        weapon: str,
        distance: int,
        opportunity: bool,
    ) -> None:
        super().__init__(res, unit=unit, target=target, weapon=weapon)
        self.distance = distance
        self.opportunity = opportunity
        self.without_los = False
        self.range_bonus = 0
        self.forbidden: str | None = None

    def allow_without_los(self) -> None:
        self.without_los = True

    def add_range(self, squares: int) -> None:
        self.range_bonus += squares

    def forbid_attack(self, reason_key: str) -> None:
        if self.forbidden is None:
            self.forbidden = reason_key


class AttackDeclared(HookContext):
    event = "attack_declared"
    _mutable = ("ap_cost",)

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        target: UnitId,
        weapon: str,
        ap_cost: int,
    ) -> None:
        super().__init__(res, unit=unit, target=target, weapon=weapon)
        self.ap_cost = ap_cost

    def set_ap_cost(self, cost: int) -> None:
        self.ap_cost = max(0, cost)


class HitsCalculating(HookContext):
    event = "hits_calculating"
    _mutable = ("hits",)

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        target: UnitId,
        weapon: str,
        hits: Fraction,
    ) -> None:
        super().__init__(res, unit=unit, target=target, weapon=weapon)
        self.hits = hits

    def add_hits(self, amount: int) -> None:
        self.hits += amount

    def multiply_hits(self, factor: Fraction) -> None:
        self.hits *= Fraction(factor)


class DamageCalculating(HookContext):
    event = "damage_calculating"
    _mutable = ("flat", "multipliers", "cover", "armor_percent")

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        target: UnitId,
        weapon: str | None,
        weapon_type: str,
        ranged: bool,
        roll: int,
        cover: bool,
        armor_percent: int,
    ) -> None:
        super().__init__(res, unit=unit, target=target, weapon=weapon)
        self.weapon_type = weapon_type
        self.ranged = ranged
        self.roll = roll
        self.cover = cover
        self.armor_percent = armor_percent
        self.flat = 0
        self.multipliers: list[Fraction] = []

    def add_damage(self, amount: int) -> None:
        self.flat += amount

    def multiply_damage(self, factor: Fraction) -> None:
        self.multipliers.append(Fraction(factor))

    def set_cover(self, value: bool) -> None:
        self.cover = value

    def set_armor_percent(self, percent: int) -> None:
        self.armor_percent = max(0, percent)


class HitAllocating(HookContext):
    event = "hit_allocating"
    _mutable = ("redirect", "prevented")

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        target: UnitId,
        weapon: str | None,
        damage: int,
    ) -> None:
        super().__init__(res, unit=unit, target=target, weapon=weapon)
        self.damage = damage
        self.redirect: UnitId | None = None
        self.prevented = False

    def redirect_hit(self, u: UnitId) -> None:
        self.redirect = u

    def prevent_hit(self) -> None:
        self.prevented = True


class AttackResolved(HookContext):
    event = "attack_resolved"
    _mutable = ("keep",)

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        target: UnitId,
        weapon: str,
        total_damage: int,
        kills: int,
    ) -> None:
        super().__init__(res, unit=unit, target=target, weapon=weapon)
        self.total_damage = total_damage
        self.kills = kills
        self.keep = False

    def keep_movement(self) -> None:
        self.keep = True


class UnitDamaged(HookContext):
    """Subject: the damaged unit; target: the source (may be None)."""

    event = "unit_damaged"

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        target: UnitId | None,
        weapon: str | None,
        damage: int,
        kills: int,
    ) -> None:
        super().__init__(res, unit=unit, target=target, weapon=weapon)
        self.damage = damage
        self.kills = kills

    @property
    def wielder(self) -> UnitId | None:
        return self.target


class ModelKilled(HookContext):
    event = "model_killed"

    def __init__(
        self, res: "Resolver", *, unit: UnitId, target: UnitId | None, role: str
    ) -> None:
        super().__init__(res, unit=unit, target=target)
        self.role = role


class UnitDestroyed(HookContext):
    event = "unit_destroyed"


class LosChecking(HookContext):
    event = "los_checking"
    _mutable = ("los", "cover")

    def __init__(
        self, res: "Resolver", *, unit: UnitId, target: UnitId, los: bool, cover: bool
    ) -> None:
        super().__init__(res, unit=unit, target=target)
        self.los = los
        self.cover = cover

    def set_los(self, value: bool) -> None:
        self.los = value

    def set_cover(self, value: bool) -> None:
        self.cover = value


class AbilityCasting(HookContext):
    event = "ability_casting"
    _mutable = ("forbidden",)

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        ability: str,
        cast_unit: UnitId | None,
        cast_square: Square | None,
    ) -> None:
        super().__init__(res, unit=unit, target=cast_unit)
        self.ability = ability
        self.cast_unit = cast_unit
        self.cast_square = cast_square
        self.forbidden: str | None = None

    def forbid_cast(self, reason_key: str) -> None:
        if self.forbidden is None:
            self.forbidden = reason_key


class AbilityCast(HookContext):
    event = "ability_cast"

    def __init__(
        self,
        res: "Resolver",
        *,
        unit: UnitId,
        ability: str,
        cast_unit: UnitId | None,
        cast_square: Square | None,
    ) -> None:
        super().__init__(res, unit=unit, target=cast_unit)
        self.ability = ability
        self.cast_unit = cast_unit
        self.cast_square = cast_square


class StatusApplied(HookContext):
    event = "status_applied"

    def __init__(self, res: "Resolver", *, unit: UnitId, status: str) -> None:
        super().__init__(res, unit=unit)
        self.status = status


class StatusExpired(HookContext):
    event = "status_expired"

    def __init__(self, res: "Resolver", *, unit: UnitId, status: str) -> None:
        super().__init__(res, unit=unit)
        self.status = status


CONTEXTS: dict[str, type[HookContext]] = {
    cls.event: cls
    for cls in (
        CombatStarted,
        RoundStarted,
        RoundEnded,
        ActivationStarted,
        ActivationEnded,
        UnitWaited,
        StatCalculating,
        StepMoving,
        StepMoved,
        OpportunityAttackTriggering,
        AttackValidating,
        AttackDeclared,
        HitsCalculating,
        DamageCalculating,
        HitAllocating,
        AttackResolved,
        UnitDamaged,
        ModelKilled,
        UnitDestroyed,
        LosChecking,
        AbilityCasting,
        AbilityCast,
        StatusApplied,
        StatusExpired,
    )
}
EVENTS: frozenset[str] = frozenset(CONTEXTS)
