import ast
from pathlib import Path

import pytest

from app.combat.ground import abilities as ability_package
from app.combat.ground.abilities.registry import REGISTRY, action
from app.combat.ground.events import HookError, LogMessage, StatusApplied
from app.combat.ground.hooks import HookContext
from app.combat.ground.ruleset import ruleset_from_raw

from .helpers import resolver, start

# --- test-only functions (registered once per process) ---------------------------------

if "test_smoke_then_fail" not in REGISTRY:

    @action("test_smoke_then_fail")
    def _smoke_then_fail(ctx: HookContext, p) -> None:
        assert ctx.owner is not None
        ctx.place_overlay(ctx.square_of(ctx.owner), "smoke", 2)
        ctx.roll("D6")
        raise RuntimeError("boom")


def _with_test_unit(raw, abilities: dict, unit_abilities: list) -> None:
    raw["abilities"].update(abilities)
    unit = dict(raw["units"]["warden"])
    unit["abilities"] = unit_abilities
    raw["units"]["test_unit"] = unit


def test_failing_function_rolls_back_its_run(raw) -> None:
    _with_test_unit(
        raw,
        {
            "test_fail": {
                "name_key": "x",
                "kind": "passive",
                "triggers": [
                    {
                        "event": "activation_started",
                        "actions": [{"fn": "test_smoke_then_fail"}],
                    }
                ],
            }
        },
        ["test_fail"],
    )
    rs = ruleset_from_raw(raw)
    state, events, rng = start(
        rs, [("test_unit", 0, (0, 0)), ("ravager_swarm", 1, (11, 11))], strict=False
    )
    # the swarm acts first; skip until the test unit activates
    from app.combat.ground.actions import Skip
    from app.combat.ground.engine import apply_action

    state, events = apply_action(rs, state, Skip(), rng)
    errors = [e for e in events if isinstance(e, HookError)]
    assert errors and errors[0].ability == "test_fail" and "boom" in errors[0].error
    assert state.overlays == ()  # the smoke placed before the error was rolled back
    assert not any(e.kind == "overlay_placed" for e in events)
    assert not any(e.kind == "rolled" and e.source == "test_fail" for e in events)

    with pytest.raises(RuntimeError, match="boom"):
        state, _, rng = start(
            rs, [("test_unit", 0, (0, 0)), ("ravager_swarm", 1, (11, 11))]
        )
        apply_action(rs, state, Skip(), rng, strict=True)


def test_trigger_cascades_are_capped(raw) -> None:
    # applying `disengage` re-applies `disengage`: an endless cascade without the cap
    _with_test_unit(
        raw,
        {
            "test_echo": {
                "name_key": "x",
                "kind": "passive",
                "triggers": [
                    {
                        "event": "status_applied",
                        "actions": [
                            {
                                "fn": "apply_status_to_owner",
                                "status": "disengage",
                                "rounds": 1,
                            }
                        ],
                    }
                ],
            }
        },
        ["test_echo"],
    )
    rs = ruleset_from_raw(raw)
    state, _, _ = start(rs, [("test_unit", 0, (0, 0)), ("ravager_swarm", 1, (11, 11))])
    res = resolver(rs, state)
    res.apply_status(0, "disengage", 1)
    applied = [e for e in res.events if isinstance(e, StatusApplied)]
    assert len(applied) == rs.rules.max_trigger_depth + 1


def test_dispatch_order_is_priority_then_turn_order(raw) -> None:
    def logger(key: str, priority: int) -> dict:
        return {
            "name_key": "x",
            "kind": "passive",
            "triggers": [
                {
                    "event": "round_started",
                    "scope": "any",
                    "priority": priority,
                    "actions": [{"fn": "log_message", "key": key}],
                }
            ],
        }

    _with_test_unit(
        raw,
        {"test_low": logger("low", 0), "test_high": logger("high", 5)},
        ["test_low", "test_high"],
    )
    rs = ruleset_from_raw(raw)
    state, events, _ = start(
        rs, [("test_unit", 0, (0, 0)), ("test_unit", 1, (11, 11))], seed=4
    )
    messages = [(e.key) for e in events if isinstance(e, LogMessage)]
    assert messages == ["high", "high", "low", "low"]
    # replaying gives the same order
    again = [
        e.key
        for e in start(
            rs, [("test_unit", 0, (0, 0)), ("test_unit", 1, (11, 11))], seed=4
        )[1]
        if isinstance(e, LogMessage)
    ]
    assert again == messages


FORBIDDEN_IMPORTS = {
    "random",
    "time",
    "datetime",
    "os",
    "io",
    "socket",
    "asyncio",
    "threading",
    "sqlalchemy",
    "httpx",
    "app.persistence",
    "app.api",
    "app.ws",
}


def test_ability_modules_import_nothing_impure() -> None:
    root = Path(ability_package.__file__).parent
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not any(
                    name == bad or name.startswith(bad + ".")
                    for bad in FORBIDDEN_IMPORTS
                ), f"{path.name} imports {name}"
