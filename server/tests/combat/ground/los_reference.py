"""Reference (slow, obviously-exact) line tracer used as a test oracle for
`los.crossed_squares`: a square is crossed iff the centre-to-centre segment passes
through its open interior, computed with Fractions per candidate square."""

from fractions import Fraction

Square = tuple[int, int]


def _span(p: int, d: int, low: int) -> tuple[Fraction, Fraction] | None:
    if d == 0:
        return (Fraction(0), Fraction(1)) if low < p < low + 2 else None
    t1, t2 = Fraction(low - p, d), Fraction(low + 2 - p, d)
    return (t1, t2) if t1 < t2 else (t2, t1)


def _entry(p: tuple[int, int], d: tuple[int, int], square: Square) -> Fraction | None:
    lo, hi = Fraction(0), Fraction(1)
    for axis in (0, 1):
        span = _span(p[axis], d[axis], 2 * square[axis])
        if span is None:
            return None
        lo, hi = max(lo, span[0]), min(hi, span[1])
    return lo if lo < hi else None


def reference_crossed(a: Square, b: Square) -> tuple[Square, ...]:
    if a == b:
        return ()
    p = (2 * a[0] + 1, 2 * a[1] + 1)
    d = (2 * (b[0] - a[0]), 2 * (b[1] - a[1]))
    entries = []
    for x in range(min(a[0], b[0]), max(a[0], b[0]) + 1):
        for y in range(min(a[1], b[1]), max(a[1], b[1]) + 1):
            if (x, y) in (a, b):
                continue
            t = _entry(p, d, (x, y))
            if t is not None:
                entries.append((t, (x, y)))
    entries.sort()
    return tuple(square for _, square in entries)
