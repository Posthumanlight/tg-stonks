"""JSON codec for engine values: actions, setups, outcomes. Pure.

One codec shared by persistence (combat_actions rows, combats.setup), the worker IPC
and the protocol views, so the formats can't drift apart.
"""

from typing import Any

from app.combat.ground.actions import Action, Attack, Move, Skip, UseAbility, Wait
from app.combat.ground.board import Board, Square
from app.combat.ground.setup import CombatSetup, UnitSetup
from app.combat.ground.state import Outcome

Json = dict[str, Any]


def _square(value: Any) -> Square:
    x, y = value
    if not (isinstance(x, int) and isinstance(y, int)):
        raise ValueError(f"invalid square {value!r}")
    return (x, y)


def action_to_json(action: Action) -> Json:
    match action:
        case Move(path=path):
            return {"type": "move", "path": [list(s) for s in path]}
        case Attack(weapon=weapon, target=target):
            return {"type": "attack", "weapon": weapon, "target": target}
        case UseAbility(ability=ability, target_unit=unit, target_square=square):
            return {
                "type": "ability",
                "ability": ability,
                "target_unit": unit,
                "target_square": list(square) if square is not None else None,
            }
        case Wait():
            return {"type": "wait"}
        case Skip():
            return {"type": "skip"}
    raise ValueError(f"not an action: {action!r}")


def action_from_json(data: Json) -> Action:
    try:
        match data.get("type"):
            case "move":
                return Move(tuple(_square(s) for s in data["path"]))
            case "attack":
                return Attack(str(data["weapon"]), int(data["target"]))
            case "ability":
                square = data.get("target_square")
                unit = data.get("target_unit")
                return UseAbility(
                    str(data["ability"]),
                    int(unit) if unit is not None else None,
                    _square(square) if square is not None else None,
                )
            case "wait":
                return Wait()
            case "skip":
                return Skip()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid action {data!r}") from exc
    raise ValueError(f"unknown action type in {data!r}")


def setup_to_json(setup: CombatSetup) -> Json:
    return {
        "board": {
            "width": setup.board.width,
            "height": setup.board.height,
            "terrain": list(setup.board.terrain),
        },
        "units": [
            {
                "unit_type": u.unit_type,
                "side": u.side,
                "origin": list(u.origin),
                "models": u.models,
            }
            for u in setup.units
        ],
        "factions": list(setup.factions),
    }


def setup_from_json(data: Json) -> CombatSetup:
    board = data["board"]
    return CombatSetup(
        Board(int(board["width"]), int(board["height"]), tuple(board["terrain"])),
        tuple(
            UnitSetup(
                u["unit_type"], int(u["side"]), _square(u["origin"]), u.get("models")
            )
            for u in data["units"]
        ),
        tuple(str(f) for f in data.get("factions", ())),  # absent in older records
    )


def outcome_to_json(outcome: Outcome | None) -> Json | None:
    if outcome is None:
        return None
    return {
        "winners": list(outcome.winners),
        "draw": outcome.draw,
        "reason": outcome.reason,
    }
