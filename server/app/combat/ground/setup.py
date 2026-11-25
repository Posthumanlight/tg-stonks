"""Combat setup: the board and the deployed units, validated before round 1."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.combat.ground.board import Board, Square
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.state import GroupState, UnitId, UnitState
from app.content.combat import DEFAULT_CONTENT_DIR, DemoBattle


class SetupError(ValueError):
    """The combat setup is invalid (board, unit types, sizes, placement)."""


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
        raise SetupError(f"unknown unit type {unit_type!r}")
    size = definition.default_models if models is None else models
    if not definition.models.min <= size <= definition.models.max:
        raise SetupError(
            f"{unit_type}: {size} models outside {definition.models.min}..{definition.models.max}"
        )
    fixed = sum(g.count for g in definition.groups if not g.fill)
    if size < fixed:
        raise SetupError(
            f"{unit_type}: {size} models can't fit the fixed groups ({fixed})"
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
                f"board {board.width}×{board.height} outside {rules.board_min}..{rules.board_max}"
            )
    if unknown := set(board.terrain) - set(ruleset.content.terrain):
        raise SetupError(f"unknown terrain {sorted(unknown)}")


def validate_setup(
    ruleset: CombatRuleset, setup: CombatSetup
) -> tuple[tuple[int, ...], tuple[UnitState, ...]]:
    """Check board, sides, unit sizes and placement. Returns (sides, built units)."""
    validate_board(ruleset, setup.board)
    sides = tuple(sorted({u.side for u in setup.units}))
    if len(sides) < 2:
        raise SetupError("a combat needs at least two sides")
    units = tuple(
        build_unit(ruleset, uid, u.unit_type, u.side, u.origin, u.models)
        for uid, u in enumerate(setup.units)
    )
    board, terrain = setup.board, ruleset.content.terrain
    taken: set[Square] = set()
    for unit in units:
        for square in unit.squares:
            if (
                not board.in_bounds(square)
                or not terrain[board.terrain_at(square)].passable
                or square in taken
            ):
                raise SetupError(
                    f"unit {unit.uid} ({unit.unit_type}) can't be placed at {unit.origin}"
                )
            taken.add(square)
    return sides, units


def default_board(ruleset: CombatRuleset, terrain: str = "open") -> Board:
    size = ruleset.rules.default_board
    return Board.filled(size.width, size.height, terrain)


DEMO_FILE = DEFAULT_CONTENT_DIR / "demo.toml"


def load_demo_setup(ruleset: CombatRuleset, path: Path = DEMO_FILE) -> CombatSetup:
    """The fixed hotseat demo battle, validated like any combat setup."""
    with open(path, "rb") as f:
        demo = DemoBattle.model_validate(tomllib.load(f))
    try:
        board = Board.from_rows(demo.rows, demo.legend)
    except KeyError as exc:
        raise SetupError(f"demo.toml: unknown legend character {exc}") from exc
    setup = CombatSetup(
        board,
        tuple(UnitSetup(u.type, u.side, u.origin, u.models) for u in demo.units),
    )
    validate_setup(ruleset, setup)
    return setup
