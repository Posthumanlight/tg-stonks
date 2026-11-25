"""Movement: Dijkstra over move costs, footprints, the corner rule, and opportunity
attacks when leaving an enemy's reach (docs/combat-ground.md "Board", "Engagement")."""

import heapq
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.combat.ground import events as ev
from app.combat.ground import hooks
from app.combat.ground.attack import check_attack, resolve_attack
from app.combat.ground.board import (
    NEIGHBOURS,
    Square,
    chebyshev,
    footprint,
    footprint_distance,
)
from app.combat.ground.state import CombatState, UnitId, UnitState
from app.combat.ground.view import BoardView

if TYPE_CHECKING:
    from app.combat.ground.resolver import Resolver
    from app.combat.ground.ruleset import CombatRuleset

REACH = 1  # engagement reach (opportunity attacks)


@dataclass(frozen=True, slots=True)
class MoveOption:
    destination: Square
    cost: int
    # Enemies that would get an opportunity attack along the path (preview).
    provokes: tuple[UnitId, ...]
    # The search tree the path is read from, shared by all options of one search.
    _start: Square = field(repr=False, compare=False)
    _previous: Mapping[Square, Square] = field(repr=False, compare=False)

    @property
    def path(self) -> tuple[Square, ...]:
        """Successive origins from (excluding) the unit's square to the destination.
        Built on demand: only the chosen destination ever needs it."""
        path = [self.destination]
        while path[-1] in self._previous and self._previous[path[-1]] != self._start:
            path.append(self._previous[path[-1]])
        path.reverse()
        return tuple(path)


def first_melee_weapon(ruleset: "CombatRuleset", unit: UnitState) -> str | None:
    for weapon in unit.weapons():
        if ruleset.weapon(weapon).mode == "melee":
            return weapon
    return None


def step_allowed(
    view: BoardView, uid: UnitId, frm: Square, to: Square, *, ending: bool
) -> bool:
    size = view.state.unit(uid).size
    if chebyshev(frm, to) != 1:
        return False
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    # No corner cutting past impassable terrain (units don't block corners).
    if dx and dy:
        side_a = footprint((frm[0] + dx, frm[1]), size)
        side_b = footprint((frm[0], frm[1] + dy), size)
        if not (view.terrain_passable(side_a) and view.terrain_passable(side_b)):
            return False
    return view.fits(footprint(to, size), uid, ending=ending)


def leaving_reach(
    state: CombatState, uid: UnitId, frm: Square, to: Square
) -> list[UnitId]:
    """Enemies whose reach the unit leaves by stepping frm → to."""
    mover = state.unit(uid)
    found = []
    for enemy in state.living():
        if enemy.side == mover.side:
            continue
        before = footprint_distance(frm, mover.size, enemy.origin, enemy.size) <= REACH
        after = footprint_distance(to, mover.size, enemy.origin, enemy.size) <= REACH
        if before and not after:
            found.append(enemy.uid)
    return found


class _FootprintCache:
    """Memoized footprint checks for one mover on one state (the pathfinding hot path)."""

    def __init__(self, view: BoardView, uid: UnitId) -> None:
        self.view, self.uid = view, uid
        self.size = view.state.unit(uid).size
        self._terrain: dict[Square, bool] = {}
        self._fits: dict[tuple[Square, bool], bool] = {}
        self._cost: dict[Square, int] = {}

    def terrain_ok(self, origin: Square) -> bool:
        ok = self._terrain.get(origin)
        if ok is None:
            ok = self._terrain[origin] = self.view.terrain_passable(
                footprint(origin, self.size)
            )
        return ok

    def fits(self, origin: Square, ending: bool) -> bool:
        key = (origin, ending)
        ok = self._fits.get(key)
        if ok is None:
            ok = self._fits[key] = self.view.fits(
                footprint(origin, self.size), self.uid, ending=ending
            )
        return ok

    def cost(self, origin: Square) -> int:
        cost = self._cost.get(origin)
        if cost is None:
            cost = self._cost[origin] = self.view.step_cost(
                footprint(origin, self.size)
            )
        return cost

    def step_ok(self, frm: Square, to: Square) -> bool:
        """Same rule as `step_allowed(ending=False)` for an adjacent step."""
        dx, dy = to[0] - frm[0], to[1] - frm[1]
        if (
            dx
            and dy
            and not (
                self.terrain_ok((frm[0] + dx, frm[1]))
                and self.terrain_ok((frm[0], frm[1] + dy))
            )
        ):
            return False
        return self.fits(to, False)


def reachable(view: BoardView, uid: UnitId, budget: int) -> dict[Square, MoveOption]:
    """Every destination reachable within `budget`, with the cheapest path (base costs).

    Dijkstra; ties resolve by (cost, square) heap order and first relaxation wins, so
    paths are deterministic. Hot path: lookups are bound to locals.
    """
    state = view.state
    start = state.unit(uid).origin
    cache = _FootprintCache(view, uid)
    # Every origin reachable within `budget` lies within Chebyshev distance `budget`
    # (each step moves 1 and costs >= 1): precompute that box once into flat arrays,
    # so the search loop does index lookups instead of per-step footprint checks.
    x0, y0 = start[0] - budget, start[1] - budget
    width = 2 * budget + 1
    terrain = [False] * (width * width)  # footprint terrain passable (corner rule)
    transit = [False] * (width * width)  # can pass through (friends allowed)
    costs = [0] * (width * width)
    for j in range(width):
        for i in range(width):
            origin = (x0 + i, y0 + j)
            k = j * width + i
            terrain[k] = cache.terrain_ok(origin)
            if terrain[k] and cache.fits(origin, False):
                transit[k] = True
                costs[k] = cache.cost(origin)

    best: dict[Square, int] = {start: 0}
    previous: dict[Square, Square] = {}
    heap: list[tuple[int, int, int]] = [(0, start[0], start[1])]  # (cost, x, y) order
    pop, push = heapq.heappop, heapq.heappush
    limit = budget + 1
    while heap:
        cost, x, y = pop(heap)
        if cost > best[(x, y)]:
            continue
        i, j = x - x0, y - y0
        for dx, dy in NEIGHBOURS:
            ni, nj = i + dx, j + dy
            if not (0 <= ni < width and 0 <= nj < width):
                continue  # outside the box: farther than `budget`
            k = nj * width + ni
            if not transit[k]:
                continue
            # same rule as `step_allowed(ending=False)`: no corner cutting
            if dx and dy and not (terrain[j * width + ni] and terrain[nj * width + i]):
                continue
            new_cost = cost + costs[k]
            nxt = (x + dx, y + dy)
            if new_cost < best.get(nxt, limit):
                best[nxt] = new_cost
                previous[nxt] = (x, y)
                push(heap, (new_cost, nxt[0], nxt[1]))
    fits = cache.fits

    provokes = _preview_provokes(view, uid, start, best, previous)
    return {
        square: MoveOption(square, best[square], provokes[square], start, previous)
        for square in sorted(best)
        if square != start and fits(square, True)
    }


def _preview_provokes(
    view: BoardView,
    uid: UnitId,
    start: Square,
    best: dict[Square, int],
    previous: dict[Square, Square],
) -> dict[Square, tuple[UnitId, ...]]:
    """Opportunity attacks along every path of the pathfinding tree, computed once per
    square from its parent (paths share prefixes). Same rule as `leaving_reach` plus
    one reaction per attack."""
    state, ruleset = view.state, view.ruleset
    mover = state.unit(uid)
    reactors = [
        e
        for e in state.living()
        if e.side != mover.side and e.reactions > 0 and first_melee_weapon(ruleset, e)
    ]
    in_reach: dict[tuple[UnitId, Square], bool] = {}

    def reached(enemy: UnitState, origin: Square) -> bool:
        key = (enemy.uid, origin)
        hit = in_reach.get(key)
        if hit is None:
            hit = in_reach[key] = (
                footprint_distance(origin, mover.size, enemy.origin, enemy.size)
                <= REACH
            )
        return hit

    provokes: dict[Square, tuple[UnitId, ...]] = {start: ()}
    for square in sorted(best, key=lambda s: (best[s], s)):  # parents before children
        if square == start:
            continue
        parent = previous[square]
        provoked = provokes[parent]
        for enemy in reactors:
            if (
                reached(enemy, parent)
                and not reached(enemy, square)
                and provoked.count(enemy.uid) < enemy.reactions
            ):
                provoked = provoked + (enemy.uid,)
        provokes[square] = provoked
    return provokes


def validate_path(
    view: BoardView, uid: UnitId, path: tuple[Square, ...], budget: int
) -> str | None:
    if not path:
        return "move.forbidden.empty"
    unit = view.state.unit(uid)
    frm, total = unit.origin, 0
    for i, square in enumerate(path):
        if not step_allowed(view, uid, frm, square, ending=i == len(path) - 1):
            return "move.forbidden.blocked"
        total += view.step_cost(footprint(square, unit.size))
        frm = square
    return "move.forbidden.too_far" if total > budget else None


def execute_move(res: "Resolver", uid: UnitId, path: tuple[Square, ...]) -> None:
    """Move step by step. Opportunity attacks resolve before each step that leaves reach.
    If the move stops early on a friend's square, the unit falls back to its last free
    square."""
    size = res.state.unit(uid).size
    last_free = res.state.unit(uid).origin
    for square in path:
        frm = res.state.unit(uid).origin
        squares = footprint(square, size)
        if not res.view.fits(squares, uid, ending=False):
            break
        step = hooks.StepMoving(
            res,
            unit=uid,
            from_square=frm,
            to_square=square,
            cost=res.view.step_cost(squares),
        )
        res.dispatch(step)
        active = res.state.active
        if (
            step.cancelled
            or active is None
            or active.uid != uid
            or step.cost > active.movement_left
        ):
            break
        _opportunity_attacks(res, uid, frm, square)
        if not res.state.unit(uid).alive:
            return
        if not res.view.fits(squares, uid, ending=False):
            break
        res.update_unit(uid, origin=square)
        active = res.state.active
        assert active is not None
        res.update_active(
            movement_left=active.movement_left - step.cost, moved=True, acted=True
        )
        res.emit(ev.UnitMoved(uid, frm, square, step.cost))
        res.dispatch(hooks.StepMoved(res, unit=uid, from_square=frm, to_square=square))
        if not res.state.unit(uid).alive:
            return
        if res.view.fits(squares, uid, ending=True):
            last_free = square
    unit = res.state.unit(uid)
    if unit.alive and not res.view.fits(unit.squares, uid, ending=True):
        res.update_unit(uid, origin=last_free)
        res.emit(ev.UnitRepositioned(uid, unit.origin, last_free, "blocked_end"))


def _opportunity_attacks(res: "Resolver", uid: UnitId, frm: Square, to: Square) -> None:
    candidates = [
        e
        for e in leaving_reach(res.state, uid, frm, to)
        if res.state.unit(e).reactions > 0
    ]
    candidates.sort(key=lambda e: (-res.effective_stat(e, "speed"), e))
    for enemy in candidates:
        if not res.state.unit(uid).alive:
            return
        unit = res.state.unit(enemy)
        weapon = first_melee_weapon(res.ruleset, unit)
        if not unit.alive or unit.reactions <= 0 or weapon is None:
            continue
        ctx = hooks.OpportunityAttackTriggering(
            res, unit=enemy, target=uid, weapon=weapon
        )
        res.dispatch(ctx)
        if ctx.cancelled or ctx.weapon is None:
            continue
        if check_attack(res, enemy, ctx.weapon, uid, opportunity=True) is not None:
            continue
        res.update_unit(enemy, reactions=res.state.unit(enemy).reactions - 1)
        resolve_attack(res, enemy, ctx.weapon, uid, opportunity=True)
