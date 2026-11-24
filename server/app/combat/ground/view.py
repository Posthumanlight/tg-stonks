"""A read-only view of one state: terrain with overlays, occupancy, LoS profiles.

Built lazily per state by the resolver and shared by movement and LoS.
"""

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


class BoardView:
    def __init__(self, ruleset: "CombatRuleset", state: CombatState) -> None:
        self.ruleset = ruleset
        self.state = state

    @cached_property
    def _overlays(self) -> dict[Square, list[str]]:
        found: dict[Square, list[str]] = {}
        for overlay in self.state.overlays:
            found.setdefault(overlay.square, []).append(overlay.overlay)
        return found

    @cached_property
    def _occupancy(self) -> dict[Square, UnitId]:
        occupied: dict[Square, UnitId] = {}
        for unit in self.state.units:
            if unit.alive:
                for square in unit.squares:
                    occupied[square] = unit.uid
        return occupied

    @cached_property
    def _props(self) -> dict[Square, SquareProps]:
        return {}

    def props(self, square: Square) -> SquareProps:
        cached = self._props.get(square)
        if cached is not None:
            return cached
        if not self.state.board.in_bounds(square):
            return OFF_BOARD
        content = self.ruleset.content
        base = content.terrain[self.state.board.terrain_at(square)]
        passable, cost, blocks, cover = (
            base.passable,
            base.move_cost,
            base.blocks_los,
            base.cover,
        )
        for overlay_id in self._overlays.get(square, ()):
            overlay = content.overlays[overlay_id]
            passable = overlay.passable if overlay.passable is not None else passable
            cost = overlay.move_cost if overlay.move_cost is not None else cost
            blocks = overlay.blocks_los if overlay.blocks_los is not None else blocks
            cover = overlay.cover if overlay.cover is not None else cover
        result = SquareProps(passable, cost, blocks, cover)
        self._props[square] = result
        return result

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
