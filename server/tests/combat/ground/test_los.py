import random
from dataclasses import replace

from app.combat.ground.los import base_sight, crossed_squares
from app.combat.ground.ruleset import ruleset_from_raw
from app.combat.ground.state import OverlayState
from app.combat.ground.view import BoardView

from .helpers import board, start


def test_crossed_squares_basics() -> None:
    assert crossed_squares((0, 0), (3, 0)) == ((1, 0), (2, 0))
    assert crossed_squares((0, 0), (0, 0)) == ()
    # an exact diagonal passes through corners only between (0,0)-(1,1), (1,1)-(2,2)
    assert crossed_squares((0, 0), (2, 2)) == ((1, 1),)
    # a shallow line crosses neighbouring rows
    assert set(crossed_squares((0, 0), (4, 1))) == {(1, 0), (2, 0), (2, 1), (3, 1)}


def test_crossing_is_symmetric() -> None:
    rnd = random.Random(5)
    for _ in range(400):
        a = (rnd.randrange(32), rnd.randrange(32))
        b = (rnd.randrange(32), rnd.randrange(32))
        assert set(crossed_squares(a, b)) == set(crossed_squares(b, a))


def test_sight_is_symmetric_with_terrain_and_units(ruleset) -> None:
    rnd = random.Random(9)
    for trial in range(8):
        rows = ["".join(rnd.choice("......#=f") for _ in range(16)) for _ in range(16)]
        b = board(rows)
        units = []
        taken = set()
        types = [
            "line_troopers",
            "warden",
            "bastion_walker",
            "brood_tyrant",
            "ravager_swarm",
        ]
        for i in range(8):
            for _ in range(50):
                unit_type = rnd.choice(types)
                size = ruleset.unit_def(unit_type).footprint
                x, y = rnd.randrange(16 - size + 1), rnd.randrange(16 - size + 1)
                squares = {(x + dx, y + dy) for dx in range(size) for dy in range(size)}
                if squares & taken or any(
                    b.terrain_at(s) in ("wall", "low_wall") for s in squares
                ):
                    continue
                taken |= squares
                units.append((unit_type, i % 2, (x, y)))
                break
        state, _, _ = start(ruleset, units, board_=b, seed=trial)
        view = BoardView(ruleset, state)
        for a in range(len(units)):
            for c in range(len(units)):
                if a != c:
                    assert base_sight(view, a, c).los == base_sight(view, c, a).los


def _sight(ruleset, rows, units, observer=0, target=1, **kw):
    state, _, _ = start(ruleset, units, board_=board(rows), **kw)
    return base_sight(BoardView(ruleset, state), observer, target)


ROWS_8 = ["........"] * 8


def test_wall_blocks(ruleset) -> None:
    rows = list(ROWS_8)
    rows[3] = "...#...."
    s = _sight(ruleset, rows, [("warden", 0, (0, 3)), ("warden", 1, (6, 3))])
    assert not s.los


def test_low_wall_gives_cover_next_to_target_only(ruleset) -> None:
    rows = list(ROWS_8)
    rows[3] = ".....=.."
    s = _sight(ruleset, rows, [("warden", 0, (0, 3)), ("warden", 1, (6, 3))])
    assert s.los and s.cover
    # flank: shooting along the wall's side, the line misses the wall square
    s = _sight(ruleset, rows, [("warden", 0, (6, 0)), ("warden", 1, (6, 3))])
    assert s.los and not s.cover
    # the wall is next to the shooter, not the target
    rows[3] = ".=......"
    s = _sight(ruleset, rows, [("warden", 0, (0, 3)), ("warden", 1, (6, 3))])
    assert s.los and not s.cover


def test_wall_next_to_both_gives_no_cover(ruleset) -> None:
    rows = list(ROWS_8)
    rows[3] = "..=....."
    s = _sight(ruleset, rows, [("warden", 0, (1, 3)), ("warden", 1, (3, 3))])
    assert s.los and not s.cover


def test_area_cover_from_any_direction(ruleset) -> None:
    rows = list(ROWS_8)
    rows[4] = "....f..."
    for observer in [(0, 4), (4, 0), (7, 7)]:
        s = _sight(ruleset, rows, [("warden", 0, observer), ("warden", 1, (4, 4))])
        assert s.los and s.cover


def test_two_by_two_needs_two_area_squares(ruleset) -> None:
    rows = list(ROWS_8)
    rows[4] = "....f..."
    s = _sight(ruleset, rows, [("warden", 0, (0, 0)), ("brood_tyrant", 1, (4, 4))])
    assert s.los and not s.cover
    rows[5] = "....f..."
    s = _sight(ruleset, rows, [("warden", 0, (0, 0)), ("brood_tyrant", 1, (4, 4))])
    assert s.los and s.cover


def test_big_units_block(ruleset) -> None:
    s = _sight(
        ruleset,
        ROWS_8,
        [("warden", 0, (0, 3)), ("warden", 1, (7, 3)), ("bastion_walker", 0, (3, 3))],
    )
    assert not s.los


def test_infantry_screens_as_cover(ruleset) -> None:
    units = [("warden", 0, (0, 3)), ("warden", 1, (6, 3)), ("line_troopers", 1, (5, 3))]
    s = _sight(ruleset, ROWS_8, units)
    assert s.los and s.cover
    # a screen that isn't next to the target gives nothing
    units[2] = ("line_troopers", 1, (2, 3))
    s = _sight(ruleset, ROWS_8, units)
    assert s.los and not s.cover


def test_friendly_screens_can_be_turned_off(ruleset, raw) -> None:
    units = [("warden", 0, (0, 3)), ("warden", 1, (6, 3)), ("line_troopers", 0, (5, 3))]
    assert _sight(ruleset, ROWS_8, units).cover
    raw["rules"]["friendly_units_screen"] = False
    s = _sight(ruleset_from_raw(raw), ROWS_8, units)
    assert s.los and not s.cover
    # enemy screens still count
    units[2] = ("line_troopers", 1, (5, 3))
    assert _sight(ruleset_from_raw(raw), ROWS_8, units).cover


def test_smoke_overlay_blocks(ruleset) -> None:
    state, _, _ = start(
        ruleset, [("warden", 0, (0, 3)), ("warden", 1, (6, 3))], board_=board(ROWS_8)
    )
    assert base_sight(BoardView(ruleset, state), 0, 1).los
    smoky = replace(state, overlays=(OverlayState((3, 3), "smoke", 2),))
    assert not base_sight(BoardView(ruleset, smoky), 0, 1).los
