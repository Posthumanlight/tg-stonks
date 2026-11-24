"""Movement: Dijkstra over move costs, footprints, the corner rule, and opportunity
attacks when leaving an enemy's reach (docs/combat-ground.md "Board", "Engagement")."""

import heapq
from dataclasses import dataclass
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
    path: tuple[Square, ...]
    provokes: tuple[
        UnitId, ...
    ]  # enemies that would get an opportunity attack (preview)


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
    if (
        dx and dy
    ):  # no corner cutting past impassable terrain (units don't block corners)
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


def reachable(view: BoardView, uid: UnitId, budget: int) -> dict[Square, MoveOption]:
    """Every destination reachable within `budget`, with the cheapest path (base costs)."""
    state, ruleset = view.state, view.ruleset
    unit = state.unit(uid)
    start = unit.origin
    best: dict[Square, int] = {start: 0}
    previous: dict[Square, Square] = {}
    heap: list[tuple[int, Square]] = [(0, start)]
    while heap:
        cost, square = heapq.heappop(heap)
        if cost > best[square]:
            continue
        for dx, dy in NEIGHBOURS:
            nxt = (square[0] + dx, square[1] + dy)
            if not step_allowed(view, uid, square, nxt, ending=False):
                continue
            new_cost = cost + view.step_cost(footprint(nxt, unit.size))
            if new_cost <= budget and new_cost < best.get(nxt, budget + 1):
                best[nxt] = new_cost
                previous[nxt] = square
                heapq.heappush(heap, (new_cost, nxt))

    options: dict[Square, MoveOption] = {}
    for square in sorted(best):
        if square == start or not view.fits(
            footprint(square, unit.size), uid, ending=True
        ):
            continue
        path = [square]
        while path[-1] in previous and previous[path[-1]] != start:
            path.append(previous[path[-1]])
        path.reverse()
        options[square] = MoveOption(
            square,
            best[square],
            tuple(path),
            _preview_provokes(ruleset, state, uid, path),
        )
    return options


def _preview_provokes(
    ruleset: "CombatRuleset", state: CombatState, uid: UnitId, path: list[Square]
) -> tuple[UnitId, ...]:
    reactions = {u.uid: u.reactions for u in state.units}
    provoked: list[UnitId] = []
    frm = state.unit(uid).origin
    for to in path:
        for enemy in leaving_reach(state, uid, frm, to):
            if reactions[enemy] > 0 and first_melee_weapon(ruleset, state.unit(enemy)):
                reactions[enemy] -= 1
                provoked.append(enemy)
        frm = to
    return tuple(provoked)


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
