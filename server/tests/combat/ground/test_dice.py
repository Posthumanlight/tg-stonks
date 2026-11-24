from fractions import Fraction

import pytest

from app.combat.ground.dice import Dice
from app.combat.ground.events import Rolled

from .helpers import resolver, start


@pytest.mark.parametrize(
    "text, expected",
    [
        ("3", Dice(0, 0, 3)),
        (4, Dice(0, 0, 4)),
        ("D6", Dice(1, 6, 0)),
        ("d3+1", Dice(1, 3, 1)),
        ("2D6+2", Dice(2, 6, 2)),
        ("2D6-1", Dice(2, 6, -1)),
    ],
)
def test_parse(text: str | int, expected: Dice) -> None:
    assert Dice.parse(text) == expected
    assert Dice.parse(str(expected)) == expected


@pytest.mark.parametrize("bad", ["", "D", "D1", "0D6", "2X6", "-1", True, "D6+"])
def test_parse_rejects(bad: object) -> None:
    with pytest.raises(ValueError):
        Dice.parse(bad)


def test_stats() -> None:
    dice = Dice.parse("2D6+2")
    assert (dice.minimum, dice.maximum, dice.mean) == (4, 14, Fraction(9))


def test_rolls_are_in_range_and_logged(ruleset) -> None:
    state, _, _ = start(ruleset, [("warden", 0, (0, 0)), ("warden", 1, (5, 5))])
    res = resolver(ruleset, state)
    dice = Dice.parse("2D3+1")
    results = [res.roll(dice, "test") for _ in range(200)]
    assert min(results) >= 3 and max(results) <= 7
    assert len([e for e in res.events if isinstance(e, Rolled)]) == 200
    assert res.roll(Dice.parse("3"), "test") == 3  # constants don't draw


def test_stochastic_rounding_keeps_the_expectation(ruleset) -> None:
    state, _, _ = start(ruleset, [("warden", 0, (0, 0)), ("warden", 1, (5, 5))])
    res = resolver(ruleset, state, seed=11)
    assert res.round_value(Fraction(3), "t") == 3
    n = 6000
    total = sum(res.round_value(Fraction(5, 2), "t") for _ in range(n))
    assert abs(Fraction(total, n) - Fraction(5, 2)) < Fraction(1, 20)
    values = {res.round_value(Fraction(1, 3), "t") for _ in range(200)}
    assert values == {0, 1}
