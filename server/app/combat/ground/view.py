"""A read-only view of one state: terrain with overlays, occupancy, LoS profiles.

Built lazily per state by the resolver and shared by movement and LoS.
"""

from collections import OrderedDict
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from app.combat.ground.board import Square
from app.combat.ground.state import CombatState, UnitId

if TYPE_CHECKING:
    from app.combat.ground.ruleset import CombatRuleset


@dataclass(frozen=True, slots=True)
class SquareProps:
    passable: bool
    move_cost: int
    blocks_los: bool
    cover: str  # none | obstacle | area


OFF_BOARD = SquareProps(passable=False, move_cost=1, blocks_los=True, cover="none")

_GRID_CACHE_SIZE = 32
# Terrain + overlays rarely change between states, so the per-square properties are
# shared by every state with the same board and overlays (keyed by identity: states,
# boards and overlay tuples are immutable).
_grid_cache: "OrderedDict[tuple[int, int, int], tuple[object, object, object, tuple[SquareProps, ...]]]" = (OrderedDict())


def terrain_grid(
    ruleset: "CombatRuleset", state: CombatState
) -> tuple[SquareProps, ...]:
    """Row-major `SquareProps` of the whole board: terrain with overlays applied."""
    key = (id(ruleset), id(state.board), id(state.overlays))
    hit = _grid_cache.get(key)
    if (
        hit is not None
        and hit[0] is ruleset
        and hit[1] is state.board
        and hit[2] is state.overlays
    ):
        _grid_cache.move_to_end(key)
        return hit[3]
    content, board = ruleset.content, state.board
    overlays: dict[Square, list[str]] = {}
    for overlay in state.overlays:
        overlays.setdefault(overlay.square, []).append(overlay.overlay)
    grid: list[SquareProps] = []
    for square in board.squares():  # row-major
        base = content.terrain[board.terrain_at(square)]
        passable, cost, blocks, cover = (
            base.passable,
            base.move_cost,
            base.blocks_los,
            base.cover,
        )
        for overlay_id in overlays.get(square, ()):
            overlay = content.overlays[overlay_id]
            passable = overlay.passable if overlay.passable is not None else passable
            cost = overlay.move_cost if overlay.move_cost is not None else cost
            blocks = overlay.blocks_los if overlay.blocks_los is not None else blocks
            cover = overlay.cover if overlay.cover is not None else cover
        grid.append(SquareProps(passable, cost, blocks, cover))
    result = tuple(grid)
    _grid_cache[key] = (ruleset, state.board, state.overlays, result)
    if len(_grid_cache) > _GRID_CACHE_SIZE:
        _grid_cache.popitem(last=False)
    return result


class BoardView:
    def __init__(self, ruleset: "CombatRuleset", state: CombatState) -> None:
        self.ruleset = ruleset
        self.state = state
        # Per-state memo for pure geometry results (the state never changes under it).
        self.memo: dict[str, dict] = {}

    @cached_property
    def _occupancy(self) -> dict[Square, UnitId]:
        occupied: dict[Square, UnitId] = {}
        for unit in self.state.units:
            if unit.alive:
                for square in unit.squares:
                    occupied[square] = unit.uid
        return occupied

    @cached_property
    def _grid(self) -> tuple[SquareProps, ...]:
        return terrain_grid(self.ruleset, self.state)

    def props(self, square: Square) -> SquareProps:
        x, y = square
        board = self.state.board
        if 0 <= x < board.width and 0 <= y < board.height:
            return self._grid[y * board.width + x]
        return OFF_BOARD

    def occupant(self, square: Square) -> UnitId | None:
        return self._occupancy.get(square)

    def los_profile(self, uid: UnitId) -> str:
        unit = self.state.unit(uid)
        profile = self.ruleset.unit_def(unit.unit_type).default_los_profile
        for status in unit.statuses:  # the most recently applied override wins
            override = self.ruleset.statuses[status.status].definition.los_profile
            if override is not None:
                profile = override
        return profile

    # --- movement helpers --------------------------------------------------------------

    def terrain_passable(self, squares: tuple[Square, ...]) -> bool:
        return all(self.props(s).passable for s in squares)

    def fits(self, squares: tuple[Square, ...], mover: UnitId, *, ending: bool) -> bool:
        """Can `mover` occupy these squares? Friends may be passed through, not ended on."""
        if not self.terrain_passable(squares):
            return False
        side = self.state.unit(mover).side
        for square in squares:
            other = self.occupant(square)
            if other is None or other == mover:
                continue
            if ending or self.state.unit(other).side != side:
                return False
        return True

    def step_cost(self, squares: tuple[Square, ...]) -> int:
        return max(self.props(s).move_cost for s in squares)
