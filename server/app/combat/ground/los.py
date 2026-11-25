"""Line of sight and cover (docs/combat-ground.md "Line of sight", "Cover").

Geometry is exact and integer-only: the segment joins square centres, and a square is
crossed only if the segment passes through its interior — touching a corner or an edge
doesn't count.
"""

from dataclasses import dataclass
from functools import lru_cache

from app.combat.ground.board import Square, adjacent_to_any, chebyshev
from app.combat.ground.state import UnitId
from app.combat.ground.view import BoardView


@lru_cache(maxsize=1 << 16)
def crossed_squares(a: Square, b: Square) -> tuple[Square, ...]:
    """Squares whose interior the centre-to-centre segment a→b passes through, in order,
    excluding `a` and `b`. The *set* is symmetric in (a, b).

    Grid walk with an exact integer error term: from each square the segment leaves
    through whichever boundary it reaches first. A tie means it passes exactly through
    a corner, so it steps diagonally and the two side squares — touched only at that
    corner — are not crossed. (Checked against a brute-force oracle in the tests.)
    """
    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
    sx = 1 if b[0] > a[0] else -1
    sy = 1 if b[1] > a[1] else -1
    x, y = a
    error = dx - dy  # compares the distances (in t) to the next x and y boundaries
    crossed: list[Square] = []
    while (x, y) != b:
        if error > 0:
            x += sx
            error -= 2 * dy
        elif error < 0:
            y += sy
            error += 2 * dx
        else:
            x += sx
            y += sy
            error += 2 * (dx - dy)
        crossed.append((x, y))
    return tuple(crossed[:-1])  # drop `b`


@dataclass(frozen=True, slots=True)
class Line:
    los: bool
    cover: bool  # directional cover for the target on this line
    frm: Square
    to: Square


def trace(
    view: BoardView,
    frm: Square,
    to: Square,
    observer_squares: tuple[Square, ...],
    target_squares: tuple[Square, ...],
    observer: UnitId | None,
    target: UnitId | None,
) -> Line:
    """Evaluate one centre-to-centre line between two footprint squares."""
    exclude = set(observer_squares) | set(target_squares)
    friendly_screen = view.ruleset.rules.friendly_units_screen
    observer_side = view.state.unit(observer).side if observer is not None else None
    obstacles: list[Square] = []
    for square in crossed_squares(frm, to):
        if square in exclude:
            continue
        props = view.props(square)
        if props.blocks_los:
            return Line(False, False, frm, to)
        if props.cover == "obstacle":
            obstacles.append(square)
        occupant = view.occupant(square)
        if occupant is not None and occupant not in (observer, target):
            profile = view.los_profile(occupant)
            if profile == "block":
                return Line(False, False, frm, to)
            if profile == "screen" and (
                friendly_screen or view.state.unit(occupant).side != observer_side
            ):
                obstacles.append(square)
    cover = any(
        adjacent_to_any(s, target_squares) and not adjacent_to_any(s, observer_squares)
        for s in obstacles
    )
    return Line(True, cover, frm, to)


def best_line(
    view: BoardView,
    observer_squares: tuple[Square, ...],
    target_squares: tuple[Square, ...],
    observer: UnitId | None,
    target: UnitId | None,
) -> Line:
    """The line best for the observer: LoS first, then no cover, then shortest, then
    square order (deterministic)."""
    best: tuple[tuple[object, ...], Line] | None = None
    for frm in observer_squares:
        for to in target_squares:
            line = trace(
                view, frm, to, observer_squares, target_squares, observer, target
            )
            key = (not line.los, line.cover, chebyshev(frm, to), frm, to)
            if best is None or key < best[0]:
                best = (key, line)
    assert best is not None
    return best[1]


def area_cover(view: BoardView, target_squares: tuple[Square, ...]) -> bool:
    """1×1 needs its square in area cover; 2×2 needs at least 2 of its 4 squares."""
    needed = 1 if len(target_squares) == 1 else 2
    return sum(view.props(s).cover == "area" for s in target_squares) >= needed


@dataclass(frozen=True, slots=True)
class Sight:
    los: bool
    cover: bool  # area or directional; only meaningful for ranged attacks


def base_sight(view: BoardView, observer: UnitId, target: UnitId) -> Sight:
    """Geometry-only LoS and cover between two units (before `los_checking` hooks)."""
    a, b = view.state.unit(observer), view.state.unit(target)
    line = best_line(view, a.squares, b.squares, observer, target)
    if not line.los:
        return Sight(False, False)
    return Sight(True, line.cover or area_cover(view, b.squares))


def sight_to_square(view: BoardView, observer: UnitId, square: Square) -> bool:
    """LoS from a unit to a square (ability targeting). Memoized per state."""
    memo = view.memo.setdefault("sight_to_square", {})
    key = (observer, square)
    if key in memo:
        return memo[key]
    a = view.state.unit(observer)
    if square in a.squares:
        seen = True
    else:
        occupant = view.occupant(square)
        seen = best_line(view, a.squares, (square,), observer, occupant).los
    memo[key] = seen
    return seen
