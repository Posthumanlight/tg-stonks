"""Army building and deployment (docs/combat-ground.md "Deployment and army building")."""

import json
from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

from app.combat.ground.board import Board
from app.combat.ground.deployment import (
    Army,
    ArmyUnit,
    BattleMap,
    army_points,
    deploy,
    deploy_side,
    load_battle_map,
)
from app.combat.ground.serialize import setup_from_json, setup_to_json
from app.combat.ground.setup import Rect, SetupError, Zone, placement_issue
from app.config import REPO_ROOT
from app.content.combat import DemoBattle, parse_combat_content

PLACEMENT_CASES = json.loads(
    (REPO_ROOT / "testdata" / "placement_cases.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def zoned_map(ruleset) -> BattleMap:
    """The content map, with its deployment zones (online rooms)."""
    return load_battle_map(ruleset)


@pytest.fixture(scope="module")
def battle_map(zoned_map) -> BattleMap:
    """The same map without zones (hotseat battles)."""
    return zoned_map.free()


def _with_unit(armies: tuple[Army, ...], side: int, index: int, **changes: Any):
    army = armies[side]
    units = list(army.units)
    units[index] = replace(units[index], **changes)
    return _with_side(armies, side, replace(army, units=tuple(units)))


def _with_side(armies: tuple[Army, ...], side: int, army: Army) -> tuple[Army, ...]:
    return tuple(army if s == side else a for s, a in enumerate(armies))


def _error(
    ruleset, battle_map: BattleMap, armies
) -> tuple[str, int | None, int | None]:
    with pytest.raises(SetupError) as caught:
        deploy(ruleset, battle_map, armies)
    return caught.value.reason_key, caught.value.side, caught.value.unit


# --- the shared placement rule -----------------------------------------------------


@pytest.mark.parametrize(
    "case", PLACEMENT_CASES["cases"], ids=lambda c: c["name"].replace(" ", "_")
)
def test_placement_cases(case: dict[str, Any]) -> None:
    board = Board.from_rows(PLACEMENT_CASES["rows"], {".": "open", "#": "wall"})
    zone = (
        None if case["zone"] is None else Zone(0, tuple(Rect(*r) for r in case["zone"]))
    )
    issue = placement_issue(
        board,
        {"open": True, "wall": False},
        tuple(case["origin"]),
        case["size"],
        {tuple(s) for s in case["occupied"]},
        zone,
    )
    assert issue == case["expect"]


# --- deploy ------------------------------------------------------------------------


def test_default_armies_deploy_in_side_order(ruleset, battle_map) -> None:
    setup = deploy(ruleset, battle_map, battle_map.defaults)
    assert setup.factions == ("concord", "brood")
    sides = [u.side for u in setup.units]
    assert sides == sorted(sides)  # side 0's units first: the deployment index
    assert setup_from_json(setup_to_json(setup)) == setup


def test_records_without_factions_still_load(ruleset, battle_map) -> None:
    data = setup_to_json(deploy(ruleset, battle_map, battle_map.defaults))
    del data["factions"]
    assert setup_from_json(data).factions == ()


def test_side_wide_errors(ruleset, battle_map) -> None:
    armies = battle_map.defaults
    assert _error(
        ruleset, battle_map, _with_side(armies, 1, replace(armies[1], faction="nope"))
    ) == ("setup.unknown_faction", 1, None)
    assert _error(
        ruleset, battle_map, _with_side(armies, 0, replace(armies[0], units=()))
    ) == ("setup.empty_side", 0, None)
    limit = ruleset.rules.max_units_per_side
    crowd = tuple(ArmyUnit("warden", (x % 24, x // 24)) for x in range(limit + 1))
    assert _error(
        ruleset, battle_map, _with_side(armies, 0, replace(armies[0], units=crowd))
    ) == ("setup.too_many_units", 0, None)


def test_mirror_matches_are_allowed(ruleset, battle_map) -> None:
    concord = battle_map.defaults[0]
    mirrored = Army(
        "concord",
        tuple(
            replace(u, origin=(u.origin[0], u.origin[1] + 18)) for u in concord.units
        ),
    )
    setup = deploy(ruleset, battle_map, (concord, mirrored))
    assert setup.factions == ("concord", "concord")


@pytest.mark.parametrize(
    ("side", "index", "changes", "reason"),
    [
        (0, 2, {"unit_type": "nope"}, "setup.unknown_unit"),
        (0, 0, {"unit_type": "brood_tyrant"}, "setup.wrong_faction"),
        (0, 0, {"models": 11}, "setup.models_out_of_range"),
        (1, 1, {"origin": (10, 5)}, "setup.blocked_square"),  # a wall in demo.toml
        (0, 3, {"origin": (23, 23)}, "setup.out_of_bounds"),  # a 2×2 walker
        (1, 0, {"origin": (2, 1)}, "setup.overlap"),  # on Concord's troopers
    ],
)
def test_unit_errors_are_located(
    ruleset, battle_map, side: int, index: int, changes: dict, reason: str
) -> None:
    armies = _with_unit(battle_map.defaults, side, index, **changes)
    assert _error(ruleset, battle_map, armies) == (reason, side, index)


def test_deployment_zones(ruleset, zoned_map, battle_map) -> None:
    assert zoned_map.zones is not None and battle_map.zones is None
    deploy(ruleset, zoned_map, zoned_map.defaults)  # the defaults fit the zones
    armies = _with_unit(zoned_map.defaults, 0, 2, origin=(4, 10))
    assert _error(ruleset, zoned_map, armies) == ("setup.outside_zone", 0, 2)
    deploy(ruleset, battle_map, armies)  # without zones the whole board is allowed


def test_points_limit(ruleset, battle_map) -> None:
    concord, brood = battle_map.defaults
    assert (army_points(ruleset, concord), army_points(ruleset, brood)) == (440, 365)
    with pytest.raises(SetupError) as caught:
        deploy(ruleset, battle_map, battle_map.defaults, points_limit=400)
    assert (caught.value.reason_key, caught.value.side) == ("setup.over_points", 0)
    for unlimited in (None, 0):
        deploy(ruleset, battle_map, battle_map.defaults, points_limit=unlimited)


def test_one_side_alone(ruleset, zoned_map) -> None:
    """An online player's Ready: their army, checked without the opponent's."""
    concord, brood = zoned_map.defaults
    deploy_side(ruleset, zoned_map, 0, concord)
    deploy_side(ruleset, zoned_map, 1, brood, points_limit=365)
    with pytest.raises(SetupError) as caught:
        deploy_side(ruleset, zoned_map, 1, concord)  # Concord's spots are side 0's zone
    assert (caught.value.reason_key, caught.value.side, caught.value.unit) == (
        "setup.outside_zone",
        1,
        0,
    )
    stacked = replace(concord, units=(concord.units[0], concord.units[0]))
    with pytest.raises(SetupError, match="placed") as caught:
        deploy_side(ruleset, zoned_map, 0, stacked)
    assert caught.value.reason_key == "setup.overlap"
    with pytest.raises(SetupError) as caught:
        deploy_side(ruleset, zoned_map, 0, concord, points_limit=400)
    assert caught.value.reason_key == "setup.over_points"
    with pytest.raises(SetupError) as caught:
        deploy_side(ruleset, zoned_map, 2, concord)
    assert caught.value.reason_key == "combat.bad_setup"


def test_wrong_number_of_sides(ruleset, battle_map) -> None:
    reason, _, _ = _error(ruleset, battle_map, battle_map.defaults[:1])
    assert reason == "combat.bad_setup"


# --- content -----------------------------------------------------------------------


def test_units_need_a_known_faction(raw) -> None:
    raw["units"]["warden"]["faction"] = "nope"
    with pytest.raises(ValidationError, match="unknown faction"):
        parse_combat_content(raw)
    del raw["units"]["warden"]["faction"]
    with pytest.raises(ValidationError):
        parse_combat_content(raw)


def test_demo_zones_need_one_per_side() -> None:
    demo = {
        "factions": ["concord", "brood"],
        "width": 1,
        "height": 1,
        "legend": {".": "open"},
        "rows": ["."],
        "units": [
            {"type": "warden", "side": 0, "origin": [0, 0]},
            {"type": "warden", "side": 1, "origin": [0, 0]},
        ],
        "deployment": {"zones": [{"side": 0, "rects": [[0, 0, 1, 1]]}]},
    }
    with pytest.raises(ValidationError, match="one zone per side"):
        DemoBattle.model_validate(demo)


def test_pvp_presets_are_checked(raw) -> None:
    raw["rules"]["pvp"]["timer_presets"] = [60, 0]  # without the default 45
    with pytest.raises(ValidationError, match="activation_timer_s"):
        parse_combat_content(raw)
    raw["rules"]["pvp"]["timer_presets"] = [45, 45]
    with pytest.raises(ValidationError, match="distinct"):
        parse_combat_content(raw)
