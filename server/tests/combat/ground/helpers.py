"""Shared builders for ground-combat tests: ASCII boards, quick setups, forced turns."""

import random
from collections.abc import Sequence
from dataclasses import replace

from app.combat.ground.board import Board, Square
from app.combat.ground.engine import start_combat
from app.combat.ground.resolver import Resolver
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.setup import CombatSetup, UnitSetup
from app.combat.ground.state import Activation, CombatState

LEGEND = {
    ".": "open",
    "#": "wall",
    "=": "low_wall",
    "r": "rubble",
    "f": "forest",
    "~": "deep_water",
}


def board(rows: Sequence[str]) -> Board:
    return Board.from_rows(rows, LEGEND)


def open_board(width: int = 12, height: int = 12) -> Board:
    return Board.filled(width, height)


def start(
    ruleset: CombatRuleset,
    units: Sequence[tuple[str, int, Square] | tuple[str, int, Square, int]],
    *,
    board_: Board | None = None,
    seed: int = 1,
    strict: bool = True,
) -> tuple[CombatState, list, random.Random]:
    """Start a combat; `units` are (type, side, origin[, models])."""
    rng = random.Random(seed)
    setup = CombatSetup(
        board_ or open_board(),
        tuple(UnitSetup(u[0], u[1], u[2], u[3] if len(u) > 3 else None) for u in units),  # type: ignore[misc]
    )
    state, events = start_combat(ruleset, setup, rng, strict=strict)
    return state, events, rng


def activate(
    ruleset: CombatRuleset,
    state: CombatState,
    uid: int,
    *,
    movement: int | None = None,
    ap: int | None = None,
) -> CombatState:
    """Force `uid` to be the active unit (bypasses turn order; for focused tests)."""
    definition = ruleset.unit_def(state.unit(uid).unit_type)
    active = Activation(
        uid,
        definition.movement if movement is None else movement,
        definition.action_points if ap is None else ap,
    )
    return replace(
        state,
        active=active,
        queue=tuple(u for u in state.queue if u != uid),
        wait_queue=tuple(u for u in state.wait_queue if u != uid),
    )


def resolver(
    ruleset: CombatRuleset, state: CombatState, *, seed: int = 0, strict: bool = True
) -> Resolver:
    return Resolver(ruleset, state, random.Random(seed), strict=strict)


def kinds(events: list) -> list[str]:
    return [e.kind for e in events]
