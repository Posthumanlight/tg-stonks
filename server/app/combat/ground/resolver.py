"""The working object behind one engine call: current state, logged randomness, hook
dispatch, and the effects ability functions can invoke.

State stays immutable: every change replaces `self.state`. That makes trigger runs
transactional — a failing run restores the previous state, RNG state and event log.
"""

import random
from dataclasses import replace
from fractions import Fraction
from typing import Any

from app.combat.ground import events as ev
from app.combat.ground import hooks
from app.combat.ground.board import Square, footprint, footprint_distance
from app.combat.ground.dice import Dice
from app.combat.ground.los import Sight, area_cover, base_sight
from app.combat.ground.ruleset import BoundTrigger, CombatRuleset, Condition
from app.combat.ground.state import CombatState, OverlayState, StatusState, UnitId
from app.combat.ground.view import BoardView
from app.content.combat import Unit

STATS = ("speed", "movement", "action_points", "reactions")


class IllegalAction(ValueError):
    """The action breaks the rules. `reason` is an i18n key."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Resolver:
    def __init__(
        self,
        ruleset: CombatRuleset,
        state: CombatState,
        rng: random.Random,
        *,
        strict: bool = False,
        preview: bool = False,
    ) -> None:
        self.ruleset = ruleset
        self.state = state
        self.rng = rng
        self.strict = strict  # re-raise errors from hooked functions (tests)
        self.preview = preview  # legal-action previews: results are thrown away
        self.events: list[ev.Event] = []
        self.depth = 0
        self.end_requested = False
        self._view: BoardView | None = None
        self._sight: dict[tuple[UnitId, UnitId], Sight] = {}

    # --- state helpers -----------------------------------------------------------------

    @property
    def view(self) -> BoardView:
        if self._view is None or self._view.state is not self.state:
            self._view = BoardView(self.ruleset, self.state)
            self._sight = {}
        return self._view

    def emit(self, event: ev.Event) -> None:
        self.events.append(event)

    def unit_def(self, uid: UnitId) -> Unit:
        return self.ruleset.unit_def(self.state.unit(uid).unit_type)

    def update_unit(self, uid: UnitId, **changes: Any) -> None:
        self.state = self.state.with_unit(replace(self.state.unit(uid), **changes))

    def update_active(self, **changes: Any) -> None:
        assert self.state.active is not None
        self.state = replace(self.state, active=replace(self.state.active, **changes))

    def remove_from_queues(self, uid: UnitId) -> None:
        self.state = replace(
            self.state,
            queue=tuple(u for u in self.state.queue if u != uid),
            wait_queue=tuple(u for u in self.state.wait_queue if u != uid),
        )

    # --- randomness (every draw is logged) ----------------------------------------------

    def roll(self, dice: Dice, source: str) -> int:
        if dice.count == 0:
            return dice.const
        values = tuple(self.rng.randint(1, dice.sides) for _ in range(dice.count))
        result = sum(values) + dice.const
        self.emit(ev.Rolled(source or "rules", "dice", str(dice), values, result))
        return result

    def chance(self, percent: int, source: str) -> bool:
        draw = self.rng.randrange(100)
        result = draw < percent
        self.emit(
            ev.Rolled(source or "rules", "chance", f"{percent}%", (draw,), int(result))
        )
        return result

    def round_value(self, value: Fraction, source: str) -> int:
        """Stochastic rounding: floor, +1 with probability = fractional part (logged)."""
        value = Fraction(value)
        floor = value.numerator // value.denominator
        rest = value - floor
        if rest == 0:
            return floor
        draw = self.rng.randrange(rest.denominator)
        result = floor + (1 if draw < rest.numerator else 0)
        self.emit(ev.Rolled(source or "rules", "round", str(value), (draw,), result))
        return result

    # --- stats, sight, engagement ------------------------------------------------------

    def base_stat(self, uid: UnitId, stat: str) -> int:
        if stat == "reactions":
            return self.ruleset.rules.base_reactions
        if stat not in STATS:
            raise ValueError(f"unknown stat {stat!r}")
        return int(getattr(self.unit_def(uid), stat))

    def effective_stat(self, uid: UnitId, stat: str) -> int:
        base = self.base_stat(uid, stat)
        ctx = hooks.StatCalculating(self, unit=uid, stat=stat, value=base)
        self.dispatch(ctx)
        value = Fraction(base + ctx.bonus)
        for factor in ctx.multipliers:
            value *= factor
        return max(0, value.numerator // value.denominator)

    def sight(self, observer: UnitId, target: UnitId) -> Sight:
        view = self.view
        key = (observer, target)
        cached = self._sight.get(key)
        if cached is not None:
            return cached
        base = base_sight(view, observer, target)
        ctx = hooks.LosChecking(
            self, unit=observer, target=target, los=base.los, cover=base.cover
        )
        self.dispatch(ctx)
        result = Sight(ctx.los, ctx.cover)
        if self.state is view.state:
            self._sight[key] = result
        return result

    def cover_for(self, attacker: UnitId, target: UnitId) -> bool:
        """Cover for a ranged hit: from the line of fire, or area cover without LoS."""
        sight = self.sight(attacker, target)
        if sight.los:
            return sight.cover
        return area_cover(self.view, self.state.unit(target).squares)

    def is_engaged(self, uid: UnitId) -> bool:
        unit = self.state.unit(uid)
        return any(
            other.side != unit.side
            and footprint_distance(unit.origin, unit.size, other.origin, other.size)
            <= 1
            for other in self.state.living()
        )

    def total_hp(self, uid: UnitId) -> int:
        unit = self.state.unit(uid)
        total = sum(g.alive * g.hp for g in unit.groups)
        if unit.wounded is not None:
            group, hp_left = unit.wounded
            total -= unit.groups[group].hp - hp_left
        return total

    # --- hook dispatch -----------------------------------------------------------------

    def dispatch(self, ctx: hooks.HookContext) -> None:
        if self.depth >= self.ruleset.rules.max_trigger_depth:
            return  # cascade cap: the event still happened, no further triggers fire
        for _, trigger, owner, source in self._collect(ctx):
            owner_unit = self.state.unit(owner)
            if not owner_unit.alive and owner not in (ctx.unit, ctx.target):
                continue
            self.run_trigger(trigger.conditions, trigger.actions, ctx, owner, source)

    def _collect(
        self, ctx: hooks.HookContext
    ) -> list[tuple[tuple[int, ...], BoundTrigger, UnitId, str]]:
        state, ruleset, event = self.state, self.ruleset, ctx.event
        order = {uid: i for i, uid in enumerate(state.round_order)}

        def position(uid: UnitId) -> int:
            return order.get(uid, len(order) + uid)

        found: list[tuple[tuple[int, ...], BoundTrigger, UnitId, str]] = []
        wielder = ctx.wielder
        if ctx.weapon is not None and wielder is not None:
            for ai, bound in enumerate(ruleset.weapon_abilities.get(ctx.weapon, ())):
                for trig in bound.by_event.get(event, ()):
                    key = (-trig.priority, position(wielder), 0, ai, trig.index)
                    found.append((key, trig, wielder, bound.ability_id))
        involved = (ctx.unit, ctx.target)
        for unit in state.units:
            if not unit.alive and unit.uid not in involved:
                continue
            sources = [
                (1, ai, b)
                for ai, b in enumerate(ruleset.unit_abilities[unit.unit_type])
            ]
            sources += [
                (2, si, ruleset.statuses[s.status])
                for si, s in enumerate(unit.statuses)
            ]
            for kind, ai, bound in sources:
                for trig in bound.by_event.get(event, ()):
                    if self._scope_ok(trig.scope, unit.uid, ctx):
                        key = (-trig.priority, position(unit.uid), kind, ai, trig.index)
                        found.append((key, trig, unit.uid, bound.ability_id))
        found.sort(key=lambda entry: entry[0])
        return found

    def _scope_ok(self, scope: str, owner: UnitId, ctx: hooks.HookContext) -> bool:
        if scope == "any":
            return True
        if scope == "self":
            return ctx.unit == owner
        if scope == "self_target":
            return ctx.target == owner
        if ctx.unit is None or ctx.unit == owner:
            return False
        same_side = self.state.unit(ctx.unit).side == self.state.unit(owner).side
        return same_side if scope == "ally" else not same_side

    def run_trigger(
        self,
        conditions: tuple[Condition, ...],
        actions: tuple[Any, ...],
        ctx: hooks.HookContext,
        owner: UnitId,
        source: str,
    ) -> None:
        """Run one trigger transactionally: all of it commits, or none of it."""
        saved = (
            self.state,
            self.rng.getstate(),
            len(self.events),
            ctx._snapshot(),
            self.end_requested,
        )
        previous = (ctx.owner, ctx.source)
        ctx.owner, ctx.source = owner, source
        self.depth += 1
        try:
            if all(c(ctx) for c in conditions):
                for act in actions:
                    act(ctx)
        except Exception as exc:  # a hooked function failed: roll back its whole run
            if self.strict:
                raise
            self.state, rng_state, n_events, ctx_snapshot, self.end_requested = saved
            self.rng.setstate(rng_state)
            del self.events[n_events:]
            ctx._restore(ctx_snapshot)
            self.emit(ev.HookError(source, ctx.event, f"{type(exc).__name__}: {exc}"))
        finally:
            self.depth -= 1
            ctx.owner, ctx.source = previous

    # --- damage ------------------------------------------------------------------------

    def apply_damage(
        self,
        victim: UnitId,
        amount: int,
        *,
        source: UnitId | None,
        weapon: str | None,
        index: int = 0,
        cover: bool = False,
    ) -> tuple[int, str | None]:
        """One hit on one model: the wounded model, else the lowest casualty priority.
        Excess damage is lost (no spill). Returns (applied, killed role or None)."""
        unit = self.state.unit(victim)
        if amount <= 0 or not unit.alive:
            self.emit(
                ev.HitResolved(
                    source if source is not None else -1,
                    victim,
                    index,
                    max(amount, 0),
                    0,
                    cover,
                    None,
                )
            )
            return 0, None
        if unit.wounded is not None:
            group_index, hp_left = unit.wounded
        else:
            group_index = min(
                (g.casualty_priority, i) for i, g in enumerate(unit.groups) if g.alive
            )[1]
            hp_left = unit.groups[group_index].hp
        applied = min(amount, hp_left)
        groups = list(unit.groups)
        killed: str | None = None
        if hp_left - applied == 0:
            group = groups[group_index]
            groups[group_index] = replace(group, alive=group.alive - 1)
            wounded = None
            killed = group.role
        else:
            wounded = (group_index, hp_left - applied)
        self.update_unit(victim, groups=tuple(groups), wounded=wounded)
        self.emit(
            ev.HitResolved(
                source if source is not None else -1,
                victim,
                index,
                amount,
                applied,
                cover,
                killed,
            )
        )
        self.dispatch(
            hooks.UnitDamaged(
                self,
                unit=victim,
                target=source,
                weapon=weapon,
                damage=applied,
                kills=1 if killed else 0,
            )
        )
        if killed is not None:
            self.emit(ev.ModelKilled(victim, killed, source))
            self.dispatch(
                hooks.ModelKilled(self, unit=victim, target=source, role=killed)
            )
            if not self.state.unit(victim).alive:
                self.emit(ev.UnitDestroyed(victim, source))
                self.remove_from_queues(victim)
                self.dispatch(hooks.UnitDestroyed(self, unit=victim, target=source))
        return applied, killed

    def deal_hits(
        self,
        source: UnitId,
        target: UnitId,
        hits: int,
        dice: Dice,
        weapon_type: str,
        ranged: bool,
    ) -> int:
        from app.combat.ground.attack import resolve_hits

        if weapon_type not in self.ruleset.content.damage_table:
            raise ValueError(f"unknown weapon type {weapon_type!r}")
        if hits <= 0 or not self.state.unit(target).alive:
            return 0
        cover = ranged and self.cover_for(source, target)
        total, _ = resolve_hits(
            self,
            source,
            target,
            hits,
            dice,
            weapon_type,
            ranged,
            cover=cover,
            weapon=None,
        )
        return total

    def free_attack(self, source: UnitId, target: UnitId, weapon: str) -> None:
        from app.combat.ground.attack import check_attack, resolve_attack

        if check_attack(self, source, weapon, target, free=True) is None:
            resolve_attack(self, source, weapon, target, free=True)

    # --- other effects -----------------------------------------------------------------

    def heal(self, uid: UnitId, amount: int) -> int:
        unit = self.state.unit(uid)
        if amount <= 0 or not unit.alive or unit.wounded is None:
            return 0
        group_index, hp_left = unit.wounded
        full = unit.groups[group_index].hp
        healed = min(amount, full - hp_left)
        new_hp = hp_left + healed
        self.update_unit(uid, wounded=None if new_hp >= full else (group_index, new_hp))
        self.emit(ev.Healed(uid, healed))
        return healed

    def revive_models(self, uid: UnitId, count: int) -> int:
        unit = self.state.unit(uid)
        if count <= 0 or not unit.alive:
            return 0
        groups = list(unit.groups)
        revived = 0
        for i in sorted(
            range(len(groups)), key=lambda i: (groups[i].casualty_priority, i)
        ):
            room = min(groups[i].initial - groups[i].alive, count - revived)
            if room > 0:
                groups[i] = replace(groups[i], alive=groups[i].alive + room)
                revived += room
        if revived:
            self.update_unit(uid, groups=tuple(groups))
            self.emit(ev.ModelsRevived(uid, revived))
        return revived

    def apply_status(self, uid: UnitId, status: str, rounds: int) -> None:
        bound = self.ruleset.statuses.get(status)
        if bound is None:
            raise ValueError(f"unknown status {status!r}")
        unit = self.state.unit(uid)
        if not unit.alive:
            return
        definition = bound.definition
        statuses = list(unit.statuses)
        existing = next((i for i, s in enumerate(statuses) if s.status == status), None)
        if existing is None:
            new = StatusState(status, rounds, 1)
            statuses.append(new)
        elif definition.stacking == "ignore":
            return
        else:
            old = statuses.pop(existing)
            stacks = old.stacks
            if definition.stacking == "stack":
                stacks = min(definition.max_stacks, stacks + 1)
            new = StatusState(status, max(rounds, old.rounds_left), stacks)
            statuses.append(new)  # most recent last (los_profile override order)
        self.update_unit(uid, statuses=tuple(statuses))
        self.emit(ev.StatusApplied(uid, status, new.rounds_left, new.stacks))
        self.dispatch(hooks.StatusApplied(self, unit=uid, status=status))

    def remove_status(self, uid: UnitId, status: str) -> None:
        unit = self.state.unit(uid)
        if not unit.has_status(status):
            return
        self.update_unit(
            uid, statuses=tuple(s for s in unit.statuses if s.status != status)
        )
        self.emit(ev.StatusExpired(uid, status))
        self.dispatch(hooks.StatusExpired(self, unit=uid, status=status))

    def grant(self, uid: UnitId, *, ap: int = 0, movement: int = 0) -> None:
        active = self.state.active
        if active is None or active.uid != uid:
            return
        self.update_active(
            ap_left=max(0, active.ap_left + ap),
            movement_left=max(0, active.movement_left + movement),
        )

    def set_reactions(self, uid: UnitId, amount: int) -> None:
        self.update_unit(uid, reactions=max(0, amount))

    def request_end_activation(self, uid: UnitId) -> None:
        active = self.state.active
        if active is not None and active.uid == uid:
            self.end_requested = True

    def _place(self, uid: UnitId, square: Square, reason: str) -> None:
        old = self.state.unit(uid).origin
        self.update_unit(uid, origin=square)
        self.emit(ev.UnitRepositioned(uid, old, square, reason))

    def push(self, uid: UnitId, away_from: Square, squares: int) -> None:
        unit = self.state.unit(uid)
        dx = (unit.origin[0] > away_from[0]) - (unit.origin[0] < away_from[0])
        dy = (unit.origin[1] > away_from[1]) - (unit.origin[1] < away_from[1])
        if not unit.alive or (dx, dy) == (0, 0):
            return
        origin = unit.origin
        for _ in range(squares):
            nxt = (origin[0] + dx, origin[1] + dy)
            if not self.view.fits(footprint(nxt, unit.size), uid, ending=True):
                break
            origin = nxt
        if origin != unit.origin:
            self._place(uid, origin, "push")

    def teleport(self, uid: UnitId, square: Square) -> bool:
        unit = self.state.unit(uid)
        if not unit.alive or not self.view.fits(
            footprint(square, unit.size), uid, ending=True
        ):
            return False
        self._place(uid, square, "teleport")
        return True

    def spawn_unit(
        self, unit_type: str, side: int, square: Square, models: int | None
    ) -> UnitId | None:
        from app.combat.ground.setup import build_unit

        uid = len(self.state.units)
        unit = build_unit(self.ruleset, uid, unit_type, side, square, models)
        view = self.view
        if any(
            not view.props(s).passable or view.occupant(s) is not None
            for s in unit.squares
        ):
            return None
        unit = replace(unit, reactions=self.ruleset.rules.base_reactions)
        self.state = replace(self.state, units=self.state.units + (unit,))
        self.emit(ev.UnitSpawned(uid, unit_type, side, square, unit.models))
        return uid

    def place_overlay(self, square: Square, overlay: str, rounds: int) -> None:
        if overlay not in self.ruleset.content.overlays:
            raise ValueError(f"unknown overlay {overlay!r}")
        if not self.state.board.in_bounds(square) or rounds <= 0:
            return
        kept = tuple(
            o for o in self.state.overlays if (o.square, o.overlay) != (square, overlay)
        )
        self.state = replace(
            self.state, overlays=kept + (OverlayState(square, overlay, rounds),)
        )
        self.emit(ev.OverlayPlaced(square, overlay, rounds))

    def remove_overlay(self, square: Square, overlay: str) -> None:
        kept = tuple(
            o for o in self.state.overlays if (o.square, o.overlay) != (square, overlay)
        )
        if len(kept) != len(self.state.overlays):
            self.state = replace(self.state, overlays=kept)
            self.emit(ev.OverlayExpired(square, overlay))

    def log_message(self, key: str, params: dict[str, Any]) -> None:
        self.emit(
            ev.LogMessage(key, tuple(sorted((k, str(v)) for k, v in params.items())))
        )
