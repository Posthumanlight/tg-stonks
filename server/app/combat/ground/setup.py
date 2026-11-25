"""Combat setup: the board and the deployed units, validated before round 1.

Army building (factions, unit caps) lives one layer up, in `deployment.py`; this module
holds what every combat must satisfy, plus the placement check both layers share.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from app.combat.ground.board import Board, Square, footprint
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.state import GroupState, UnitId, UnitState


class SetupError(ValueError):
    """The combat setup is invalid. `reason_key` is an i18n key (docs/combat-ground.md
    "Validation and errors"); `side`/`unit` locate the entry (`unit` is the index within
    that side's units), so a client can mark the offending token."""

    def __init__(
        self,
        reason_key: str,
        message: str,
        *,
        side: int | None = None,
        unit: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_key = reason_key
        self.side = side
        self.unit = unit

    def at(self, side: int, unit: int | None) -> "SetupError":
        return SetupError(self.reason_key, str(self), side=side, unit=unit)


@dataclass(frozen=True, slots=True)
class UnitSetup:
    unit_type: str
    side: int
    origin: Square
    models: int | None = None  # default: the unit type's group counts


@dataclass(frozen=True, slots=True)
class CombatSetup:
    board: Board
    units: tuple[UnitSetup, ...]
    # One faction id per side, for labels only: the rules never read it. Empty for
    # records made before factions existed.
    factions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def contains(self, square: Square) -> bool:
        return (
            self.x <= square[0] < self.x + self.w
            and self.y <= square[1] < self.y + self.h
        )


@dataclass(frozen=True, slots=True)
class Zone:
    """A side's deployment zone: the union of its rectangles."""

    side: int
    rects: tuple[Rect, ...]

    def contains(self, square: Square) -> bool:
        return any(r.contains(square) for r in self.rects)


def placement_issue(
    board: Board,
    passable: Mapping[str, bool],
    origin: Square,
    size: int,
    occupied: Collection[Square],
    zone: Zone | None = None,
) -> str | None:
    """Why a size×size footprint at `origin` can't be placed (a `setup.*` reason key),
    or None. The one placement rule: the client mirrors it for hints, and a shared
    fixture (testdata/placement_cases.json) keeps the two in step."""
    squares = footprint(origin, size)
    if not all(board.in_bounds(s) for s in squares):
        return "setup.out_of_bounds"
    if not all(passable.get(board.terrain_at(s), False) for s in squares):
        return "setup.blocked_square"
    if zone is not None and not all(zone.contains(s) for s in squares):
        return "setup.outside_zone"
    if any(s in occupied for s in squares):
        return "setup.overlap"
    return None


def build_unit(
    ruleset: CombatRuleset,
    uid: UnitId,
    unit_type: str,
    side: int,
    origin: Square,
    models: int | None = None,
) -> UnitState:
    """A fresh unit; the `fill` group absorbs the difference to the default size."""
    definition = ruleset.content.units.get(unit_type)
    if definition is None:
        raise SetupError("setup.unknown_unit", f"unknown unit type {unit_type!r}")
    size = definition.default_models if models is None else models
    if not definition.models.min <= size <= definition.models.max:
        raise SetupError(
            "setup.models_out_of_range",
            f"{unit_type}: {size} models outside {definition.models.min}..{definition.models.max}",
        )
    fixed = sum(g.count for g in definition.groups if not g.fill)
    if size < fixed:
        raise SetupError(
            "setup.models_out_of_range",
            f"{unit_type}: {size} models can't fit the fixed groups ({fixed})",
        )
    groups = tuple(
        GroupState(
            role=g.role,
            alive=(size - fixed) if g.fill else g.count,
            initial=(size - fixed) if g.fill else g.count,
            hp=g.hp or definition.hp,
            weapons=g.weapons,
            casualty_priority=g.casualty_priority,
        )
        for g in definition.groups
    )
    return UnitState(
        uid=uid,
        unit_type=unit_type,
        side=side,
        origin=origin,
        size=definition.footprint,
        groups=groups,
    )


def validate_board(ruleset: CombatRuleset, board: Board) -> None:
    rules = ruleset.rules
    for side in (board.width, board.height):
        if not rules.board_min <= side <= rules.board_max:
            raise SetupError(
                "combat.bad_setup",
                f"board {board.width}×{board.height} outside {rules.board_min}..{rules.board_max}",
            )
    if unknown := set(board.terrain) - set(ruleset.content.terrain):
        raise SetupError("combat.bad_setup", f"unknown terrain {sorted(unknown)}")


def side_positions(units: tuple[UnitSetup, ...]) -> list[tuple[int, int]]:
    """(side, index within that side) for each unit, in setup order."""
    seen: dict[int, int] = {}
    positions = []
    for u in units:
        index = seen.get(u.side, 0)
        seen[u.side] = index + 1
        positions.append((u.side, index))
    return positions


def validate_setup(
    ruleset: CombatRuleset,
    setup: CombatSetup,
    zones: Mapping[int, Zone] | None = None,
) -> tuple[tuple[int, ...], tuple[UnitState, ...]]:
    """Check board, sides, unit sizes and placement (and deployment zones, when given:
    they apply at creation only, so replays don't need them). Returns (sides, units)."""
    validate_board(ruleset, setup.board)
    sides = tuple(sorted({u.side for u in setup.units}))
    if len(sides) < 2:
        raise SetupError("setup.empty_side", "a combat needs at least two sides")
    positions = side_positions(setup.units)
    units = []
    for uid, (u, (side, index)) in enumerate(zip(setup.units, positions)):
        try:
            units.append(
                build_unit(ruleset, uid, u.unit_type, u.side, u.origin, u.models)
            )
        except SetupError as exc:
            raise exc.at(side, index) from None
    passable = ruleset.passable_terrain
    taken: set[Square] = set()
    for unit, (side, index) in zip(units, positions):
        zone = zones.get(side) if zones is not None else None
        issue = placement_issue(
            setup.board, passable, unit.origin, unit.size, taken, zone
        )
        if issue is not None:
            raise SetupError(
                issue,
                f"unit {unit.uid} ({unit.unit_type}) can't be placed at {unit.origin}",
                side=side,
                unit=index,
            )
        taken.update(unit.squares)
    return sides, tuple(units)


def default_board(ruleset: CombatRuleset, terrain: str = "open") -> Board:
    size = ruleset.rules.default_board
    return Board.filled(size.width, size.height, terrain)
