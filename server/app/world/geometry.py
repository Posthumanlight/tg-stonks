"""2D geometry for world-gen. Integer-exact where decisions depend on it."""

Point = tuple[int, int]


def dist2(a: Point, b: Point) -> int:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def in_ellipse(x: float, y: float, a: float, b: float) -> bool:
    """True if (x, y) lies inside or on the axis-aligned ellipse x²/a² + y²/b² <= 1."""
    return x * x * b * b + y * y * a * a <= a * a * b * b


def orient(a: Point, b: Point, c: Point) -> int:
    """Sign of the cross product (b - a) x (c - a): 1 left turn, -1 right turn, 0 collinear."""
    v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (v > 0) - (v < 0)


def _within_box(a: Point, b: Point, p: Point) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[
        1
    ] <= max(a[1], b[1])


def segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    """True if segments ab and cd intersect anywhere other than one shared endpoint.

    Touching (an endpoint lying on the other segment) and collinear overlap count as
    crossing; two links meeting only at a common star do not.
    """
    shared = [p for p in (a, b) if p == c or p == d]
    if len(shared) == 2:
        return True  # the same segment
    if len(shared) == 1:
        p = shared[0]
        e = b if a == p else a
        f = d if c == p else c
        # Sharing an endpoint, they can only overlap if collinear and pointing the same way.
        same_direction = (e[0] - p[0]) * (f[0] - p[0]) + (e[1] - p[1]) * (
            f[1] - p[1]
        ) > 0
        return orient(p, e, f) == 0 and same_direction

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _within_box(a, b, c))
        or (o2 == 0 and _within_box(a, b, d))
        or (o3 == 0 and _within_box(c, d, a))
        or (o4 == 0 and _within_box(c, d, b))
    )


def point_segment_dist2(p: Point, a: Point, b: Point) -> float:
    """Squared distance from p to segment ab (+ - * / only)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return float(dist2(p, a))
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2
    t = max(0.0, min(1.0, t))
    qx = a[0] + t * dx
    qy = a[1] + t * dy
    return (p[0] - qx) ** 2 + (p[1] - qy) ** 2
