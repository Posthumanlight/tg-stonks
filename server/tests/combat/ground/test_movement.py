import pytest

from app.combat.ground.actions import Attack, Move
from app.combat.ground.board import Board, chebyshev
from app.combat.ground.engine import (
    IllegalAction,
    SetupError,
    apply_action,
    legal_actions,
)
from app.combat.ground.movement import reachable
from app.combat.ground.view import BoardView

from .helpers import activate, board, start


def _moves(ruleset, state, uid, budget):
    return reachable(BoardView(ruleset, state), uid, budget)


def test_open_board_reach_is_a_chebyshev_square(ruleset) -> None:
    state, _, _ = start(
        ruleset,
        [("warden", 0, (10, 10)), ("warden", 1, (0, 0))],
        board_=Board.filled(24, 24),
    )
    moves = _moves(ruleset, state, 0, 3)
    assert set(moves) == {
        (x, y) for x in range(7, 14) for y in range(7, 14) if (x, y) != (10, 10)
    }
    assert all(
        m.cost == chebyshev(m.destination, (10, 10)) == len(m.path)
        for m in moves.values()
    )


def test_difficult_and_impassable_terrain(ruleset) -> None:
    rows = ["........"] * 8
    rows[0] = ".r#....."
    state, _, _ = start(
        ruleset, [("warden", 0, (0, 0)), ("warden", 1, (7, 7))], board_=board(rows)
    )
    moves = _moves(ruleset, state, 0, 2)
    assert moves[(1, 0)].cost == 2  # rubble
    assert (2, 0) not in moves  # wall
    assert moves[(2, 1)].cost == 2  # around via (1, 1)


def test_no_corner_cutting(ruleset) -> None:
    rows = ["........"] * 8
    rows[0] = ".#......"
    rows[1] = "........"
    state, _, _ = start(
        ruleset, [("warden", 0, (0, 1)), ("warden", 1, (7, 7))], board_=board(rows)
    )
    moves = _moves(ruleset, state, 0, 1)
    assert (1, 0) not in moves  # wall
    rows[1] = "~......."
    state, _, _ = start(
        ruleset,
        [("warden", 0, (0, 0)), ("warden", 1, (7, 7))],
        board_=board(["." + "#" + "......"] + rows[1:]),
    )
    moves = _moves(ruleset, state, 0, 1)
    assert (1, 1) not in moves  # diagonal between wall (1,0) and water (0,1)


def test_enemies_block_friends_pass_through(ruleset) -> None:
    units = [
        ("warden", 0, (0, 3)),
        ("line_troopers", 0, (1, 3)),
        ("warden", 1, (7, 7)),
    ]
    rows = [
        "~~~~~~~~",
        "~~~~~~~~",
        "~~~~~~~~",
        "........",
        "~~~~~~~~",
        "~~~~~~~~",
        "~~~~~~~~",
        "~~~~~~~.",
    ]
    state, _, _ = start(ruleset, units, board_=board(rows))
    moves = _moves(ruleset, state, 0, 3)
    assert (1, 3) not in moves  # can't end on a friend
    assert (2, 3) in moves  # but can pass through
    units[1] = ("line_troopers", 1, (1, 3))
    state, _, _ = start(ruleset, units, board_=board(rows))
    assert _moves(ruleset, state, 0, 3) == {}


def test_two_by_two_needs_room(ruleset) -> None:
    rows = ["........"] * 8
    rows[2] = "..#....."
    state, _, _ = start(
        ruleset,
        [("brood_tyrant", 0, (0, 0)), ("warden", 1, (7, 7))],
        board_=board(rows),
    )
    moves = _moves(ruleset, state, 0, 1)
    assert (1, 1) not in moves  # its footprint would cover the wall at (2, 2)
    assert (1, 0) in moves


def test_move_action_spends_movement(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("warden", 0, (0, 0)), ("ravager_swarm", 1, (11, 11))]
    )
    state = activate(ruleset, state, 0)
    state, events = apply_action(
        ruleset, state, Move(((1, 1), (2, 2))), rng, strict=True
    )
    assert state.unit(0).origin == (2, 2)
    assert state.active.movement_left == 4
    assert [e.kind for e in events].count("unit_moved") == 2


def test_illegal_moves(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("warden", 0, (0, 0)), ("ravager_swarm", 1, (11, 11))]
    )
    state = activate(ruleset, state, 0)
    for path, reason in [
        ((), "move.forbidden.empty"),
        (((2, 2),), "move.forbidden.blocked"),
        (tuple((i, i) for i in range(1, 8)), "move.forbidden.too_far"),
    ]:
        with pytest.raises(IllegalAction) as exc:
            apply_action(ruleset, state, Move(path), rng, strict=True)
        assert exc.value.reason == reason


def test_attacking_ends_movement_unless_assault(ruleset) -> None:
    units = [("line_troopers", 0, (0, 0)), ("ravager_swarm", 1, (8, 0), 30)]
    state, _, rng = start(ruleset, units)
    state = activate(ruleset, state, 0)
    state, _ = apply_action(ruleset, state, Attack("pulse_rifle", 1), rng, strict=True)
    assert state.active.uid == 0 and state.active.movement_locked
    assert not legal_actions(ruleset, state).moves
    with pytest.raises(IllegalAction, match="after_attack"):
        apply_action(ruleset, state, Move(((0, 1),)), rng, strict=True)

    units = [("bastion_walker", 0, (0, 0)), ("spitter_brood", 1, (8, 0))]
    state, _, rng = start(ruleset, units)
    state = activate(ruleset, state, 1)
    state, _ = apply_action(
        ruleset, state, Attack("spine_spitter", 0), rng, strict=True
    )
    assert state.active.uid == 1 and state.active.ap_left == 0
    assert not state.active.movement_locked  # assault
    assert legal_actions(ruleset, state).moves


@pytest.mark.parametrize("size", [8, 32, 64])
def test_board_sizes_within_limits(ruleset, size: int) -> None:
    start(
        ruleset,
        [("warden", 0, (0, 0)), ("warden", 1, (size - 1, size - 1))],
        board_=Board.filled(size, size),
    )


@pytest.mark.parametrize("size", [7, 65])
def test_board_sizes_outside_limits(ruleset, size: int) -> None:
    with pytest.raises(SetupError):
        start(
            ruleset,
            [("warden", 0, (0, 0)), ("warden", 1, (1, 1))],
            board_=Board.filled(size, size),
        )


def test_setup_rejects_overlaps_and_walls(ruleset) -> None:
    with pytest.raises(SetupError):
        start(ruleset, [("brood_tyrant", 0, (0, 0)), ("warden", 1, (1, 1))])
    rows = ["#......."] + ["........"] * 7
    with pytest.raises(SetupError):
        start(
            ruleset, [("warden", 0, (0, 0)), ("warden", 1, (5, 5))], board_=board(rows)
        )
    with pytest.raises(SetupError):
        start(ruleset, [("warden", 0, (0, 0)), ("warden", 0, (5, 5))])  # one side only
