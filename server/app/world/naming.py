"""Name assignment and display names. See docs/world-gen.md "Names"."""

import random
from collections.abc import Sequence

_ROMAN = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def assign_names(pool: Sequence[str], count: int, rng: random.Random) -> list[str]:
    """Pick `count` distinct names. Sorting first makes the pool's file order irrelevant."""
    if count > len(pool):
        raise ValueError(f"name pool has {len(pool)} names, need {count}")
    names = sorted(pool)
    rng.shuffle(names)
    return names[:count]


def roman(number: int) -> str:
    if number < 1:
        raise ValueError("roman numerals start at 1")
    out = []
    for value, symbol in _ROMAN:
        while number >= value:
            out.append(symbol)
            number -= value
    return "".join(out)


def planet_display_name(
    star_name: str, planet_index: int, custom_name: str | None
) -> str:
    """A custom name (a delta) wins; otherwise "<Star> <Roman index>"."""
    if custom_name:
        return custom_name
    return f"{star_name} {roman(planet_index)}"
