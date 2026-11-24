"""Square grid geometry: squares, footprints, Chebyshev distance, the board."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

Square = tuple[int, int]  # (x, y), (0, 0) top-left

# Fixed order: used by pathfinding, so it is part of determinism.
NEIGHBOURS: tuple[tuple[int, int], ...] = (
    (0, -1),
    (1, 0),
    (0, 1),
    (-1, 0),
    (1, -1),
    (1, 1),
    (-1, 1),
    (-1, -1),
)


def chebyshev(a: Square, b: Square) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def footprint(origin: Square, size: int) -> tuple[Square, ...]:
    """Squares of a size×size footprint whose top-left square is `origin`."""
    ox, oy = origin
    return tuple((ox + dx, oy + dy) for dy in range(size) for dx in range(size))


def footprint_distance(a: Square, size_a: int, b: Square, size_b: int) -> int:
    """Smallest Chebyshev distance between any squares of two footprints."""
    dx = max(0, b[0] - (a[0] + size_a - 1), a[0] - (b[0] + size_b - 1))
    dy = max(0, b[1] - (a[1] + size_a - 1), a[1] - (b[1] + size_b - 1))
    return max(dx, dy)


def adjacent_to_any(square: Square, squares: Iterable[Square]) -> bool:
    return any(chebyshev(square, s) == 1 for s in squares)


@dataclass(frozen=True, slots=True)
class Board:
    width: int
    height: int
    terrain: tuple[str, ...]  # row-major terrain ids, len == width * height

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("board must be at least 1×1")
        if len(self.terrain) != self.width * self.height:
            raise ValueError("terrain length must be width * height")

    @classmethod
    def filled(cls, width: int, height: int, terrain: str = "open") -> "Board":
        return cls(width, height, (terrain,) * (width * height))

    @classmethod
    def from_rows(cls, rows: Sequence[str], legend: Mapping[str, str]) -> "Board":
        """Build from text rows, e.g. ["..#", ".=."], with legend {".": "open", ...}."""
        width = len(rows[0])
        if any(len(r) != width for r in rows):
            raise ValueError("all rows must have the same length")
        return cls(width, len(rows), tuple(legend[c] for row in rows for c in row))

    def in_bounds(self, square: Square) -> bool:
        return 0 <= square[0] < self.width and 0 <= square[1] < self.height

    def terrain_at(self, square: Square) -> str:
        return self.terrain[square[1] * self.width + square[0]]

    def with_terrain(self, square: Square, terrain: str) -> "Board":
        cells = list(self.terrain)
        cells[square[1] * self.width + square[0]] = terrain
        return Board(self.width, self.height, tuple(cells))

    def squares(self) -> Iterable[Square]:
        for y in range(self.height):
            for x in range(self.width):
                yield (x, y)
