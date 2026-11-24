"""Line of sight and cover (docs/combat-ground.md "Line of sight", "Cover").

Geometry is exact: square centres in doubled integer coordinates, Fractions for the
segment parameter. A square is crossed only if the segment passes through its interior.
"""

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache

from app.combat.ground.board import Square, adjacent_to_any, chebyshev
from app.combat.ground.state import UnitId
from app.combat.ground.view import BoardView


def _span(p: int, d: int, low: int) -> tuple[int, int, int] | None:
    """Open t-interval (n1/den, n2/den), den > 0, where coordinate p + d·t lies strictly
    inside (low, low + 2). Integers only: exact and fast."""
    if d == 0:
        return (0, 1, 1) if low < p < low + 2 else None
    if d > 0:
        return (low - p, low + 2 - p, d)
    return (p - low - 2, p - low, -d)


def _entry(p: tuple[int, int], d: tuple[int, int], square: Square) -> Fraction | None:
    """Segment parameter where it enters the square's interior, or None if it never does."""
    lo_n, lo_d, hi_n, hi_d = 0, 1, 1, 1  # the segment's own range t ∈ [0, 1]
    for axis in (0, 1):
        span = _span(p[axis], d[axis], 2 * square[axis])
        if span is None:
            return None
        n1, n2, den = span
        if n1 * lo_d > lo_n * den:  # lo = max(lo, n1/den)
            lo_n, lo_d = n1, den
        if n2 * hi_d < hi_n * den:  # hi = min(hi, n2/den)
            hi_n, hi_d = n2, den
    return Fraction(lo_n, lo_d) if lo_n * hi_d < hi_n * lo_d else None


@lru_cache(maxsize=1 << 16)
def crossed_squares(a: Square, b: Square) -> tuple[Square, ...]:
    """Squares whose interior the centre-to-centre segment a→b passes through, in order,
    excluding `a` and `b`. The *set* is symmetric in (a, b)."""
    if a == b:
        return ()
    p = (2 * a[0] + 1, 2 * a[1] + 1)
    d = (2 * (b[0] - a[0]), 2 * (b[1] - a[1]))
    candidates: set[Square] = set()
    x_lo, x_hi = sorted((a[0], b[0]))
    y_lo, y_hi = sorted((a[1], b[1]))
    if d[0] == 0:
        candidates.update((a[0], y) for y in range(y_lo, y_hi + 1))
    else:
        for x in range(x_lo, x_hi + 1):
            # t-range where the segment is within column x (closed), clipped to [0, 1]
            t1, t2 = sorted(
                (Fraction(2 * x - p[0], d[0]), Fraction(2 * x + 2 - p[0], d[0]))
            )
            t1, t2 = max(t1, Fraction(0)), min(t2, Fraction(1))
            if t1 > t2:
                continue
            ys = sorted((p[1] + d[1] * t1, p[1] + d[1] * t2))
            for y in range(
                max(y_lo, int(ys[0] // 2) - 1), min(y_hi, int(ys[1] // 2) + 1) + 1
            ):
                candidates.add((x, y))
    entries = []
    for square in candidates:
        if square in (a, b):
            continue
        t = _entry(p, d, square)
        if t is not None:
            entries.append((t, square))
    entries.sort()
    return tuple(square for _, square in entries)


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
