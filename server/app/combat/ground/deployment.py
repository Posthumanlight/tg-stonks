"""Army building and deployment for custom battles (docs/combat-ground.md "Deployment and
army building"). Pure: per-side armies + a battle map -> a validated `CombatSetup`.

The engine's own checks (unit sizes, bounds, terrain, overlap) stay in `setup.py`; this
layer adds what only army building needs: factions, unit counts, points limits and
deployment zones. Hotseat battles use `BattleMap.free()` (no zones); online rooms check
each player's side alone with `deploy_side`, then the pair with `deploy`.
"""

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from app.combat.ground.board import Board, Square
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.setup import (
    CombatSetup,
    Rect,
    SetupError,
    UnitSetup,
    Zone,
    place_units,
    validate_board,
    validate_setup,
)
from app.content.combat import DEFAULT_CONTENT_DIR, DemoBattle

DEMO_FILE = DEFAULT_CONTENT_DIR / "demo.toml"


@dataclass(frozen=True, slots=True)
class ArmyUnit:
    unit_type: str
    origin: Square
    models: int | None = None  # None: the unit type's default size


@dataclass(frozen=True, slots=True)
class Army:
    """One side: its faction and its units, in deployment order."""

    faction: str
    units: tuple[ArmyUnit, ...]


@dataclass(frozen=True, slots=True)
class BattleMap:
    """Where custom battles are fought: the board, optional deployment zones (None = the
    whole board), and the default armies (the builder's prefill, the quick battle)."""

    board: Board
    zones: tuple[Zone, ...] | None
    defaults: tuple[Army, ...]

    @property
    def sides(self) -> int:
        return len(self.defaults)

    def zone_map(self) -> dict[int, Zone] | None:
        return None if self.zones is None else {z.side: z for z in self.zones}

    def free(self) -> "BattleMap":
        """The same map with deployment allowed anywhere (hotseat battles)."""
        return replace(self, zones=None)


def army_points(ruleset: CombatRuleset, army: Army) -> int:
    """The army's points: each unit's points, whatever its model count. Unknown unit
    types count 0 (they are rejected by `check_army` anyway)."""
    units = ruleset.content.units
    return sum(units[u.unit_type].points for u in army.units if u.unit_type in units)


def check_army(
    ruleset: CombatRuleset, side: int, army: Army, points_limit: int | None = None
) -> None:
    """One side's army-building rules: faction, unit count, unit types, points limit
    (None or 0 = unlimited). Placement is checked separately."""
    content = ruleset.content
    limit = ruleset.rules.max_units_per_side
    if army.faction not in content.factions:
        raise SetupError(
            "setup.unknown_faction", f"unknown faction {army.faction!r}", side=side
        )
    if not army.units:
        raise SetupError("setup.empty_side", f"side {side} has no units", side=side)
    if len(army.units) > limit:
        raise SetupError(
            "setup.too_many_units",
            f"side {side} has more than {limit} units",
            side=side,
        )
    for index, unit in enumerate(army.units):
        definition = content.units.get(unit.unit_type)
        if definition is None:
            raise SetupError(
                "setup.unknown_unit",
                f"unknown unit type {unit.unit_type!r}",
                side=side,
                unit=index,
            )
        if definition.faction != army.faction:
            raise SetupError(
                "setup.wrong_faction",
                f"{unit.unit_type} is not a {army.faction} unit",
                side=side,
                unit=index,
            )
    if points_limit and army_points(ruleset, army) > points_limit:
        raise SetupError(
            "setup.over_points",
            f"side {side} is over the {points_limit} points limit",
            side=side,
        )


def _unit_setups(side: int, army: Army) -> tuple[UnitSetup, ...]:
    return tuple(UnitSetup(u.unit_type, side, u.origin, u.models) for u in army.units)


def deploy(
    ruleset: CombatRuleset,
    battle_map: BattleMap,
    armies: Sequence[Army],
    *,
    points_limit: int | None = None,
) -> CombatSetup:
    """Validate the armies in full and build the setup, or raise a located SetupError.
    Units are ordered side by side, each in deployment order (the turn-order
    tie-break), so the same armies always give the same setup."""
    if len(armies) != battle_map.sides:
        raise SetupError(
            "combat.bad_setup", f"expected {battle_map.sides} sides, got {len(armies)}"
        )
    for side, army in enumerate(armies):
        check_army(ruleset, side, army, points_limit)
    setup = CombatSetup(
        board=battle_map.board,
        units=tuple(u for side, a in enumerate(armies) for u in _unit_setups(side, a)),
        factions=tuple(army.faction for army in armies),
    )
    validate_setup(ruleset, setup, battle_map.zone_map())  # sizes, placement, zones
    return setup


def deploy_side(
    ruleset: CombatRuleset,
    battle_map: BattleMap,
    side: int,
    army: Army,
    *,
    points_limit: int | None = None,
) -> None:
    """Validate one side's army on its own (an online player's Ready): the army rules,
    unit sizes, and placement in that side's zone. Overlap with the other side can't
    happen when zones are disjoint, and `deploy` re-checks the pair anyway."""
    if not 0 <= side < battle_map.sides:
        raise SetupError("combat.bad_setup", f"no side {side} on this map")
    check_army(ruleset, side, army, points_limit)
    validate_board(ruleset, battle_map.board)
    place_units(
        ruleset, battle_map.board, _unit_setups(side, army), battle_map.zone_map()
    )


def load_battle_map(ruleset: CombatRuleset, path: Path = DEMO_FILE) -> BattleMap:
    """The custom-battle map from `demo.toml`. Its default armies are validated like any
    custom setup, so a bad content edit fails at startup."""
    with open(path, "rb") as f:
        demo = DemoBattle.model_validate(tomllib.load(f))
    try:
        board = Board.from_rows(demo.rows, demo.legend)
    except KeyError as exc:
        raise SetupError(
            "combat.bad_setup", f"{path.name}: unknown legend character {exc}"
        ) from exc
    zones = (
        None
        if demo.deployment is None
        else tuple(
            Zone(z.side, tuple(Rect(*r) for r in z.rects))
            for z in demo.deployment.zones
        )
    )
    defaults = tuple(
        Army(
            faction,
            tuple(
                ArmyUnit(u.type, u.origin, u.models)
                for u in demo.units
                if u.side == side
            ),
        )
        for side, faction in enumerate(demo.factions)
    )
    battle_map = BattleMap(board, zones, defaults)
    try:
        deploy(ruleset, battle_map, defaults)
    except SetupError as exc:
        raise SetupError(
            exc.reason_key,
            f"{path.name}: default armies are invalid "
            f"(side {exc.side}, unit {exc.unit}): {exc}",
        ) from exc
    return battle_map


def load_demo_setup(ruleset: CombatRuleset, path: Path = DEMO_FILE) -> CombatSetup:
    """The quick battle: the default armies on the custom-battle map."""
    battle_map = load_battle_map(ruleset, path)
    return deploy(ruleset, battle_map, battle_map.defaults)
