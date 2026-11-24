"""Combat setup: the board and the deployed units, validated before round 1."""

from dataclasses import dataclass

from app.combat.ground.board import Board, Square
from app.combat.ground.state import GroupState, UnitState, UnitId
from app.combat.ground.ruleset import CombatRuleset


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


def default_board(ruleset: CombatRuleset, terrain: str = "open") -> Board:
    size = ruleset.rules.default_board
    return Board.filled(size.width, size.height, terrain)
