"""Dice expressions: "3", "D6", "D3+1", "2D6+2", "2D6-1". Rolling lives in the resolver."""

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

_DICE_RE = re.compile(r"^(\d*)[dD](\d+)(?:([+-])(\d+))?$")
MAX_DICE = 100


@dataclass(frozen=True, slots=True)
class Dice:
    count: int  # number of dice (0 = constant only)
    sides: int  # faces per die (0 when count == 0)
    const: int

    @classmethod
    def parse(cls, value: Any) -> "Dice":
        if isinstance(value, Dice):
            return value
        if isinstance(value, bool):
            raise ValueError("dice must be an int or an expression like 'D6+1'")
        if isinstance(value, int):
            if value < 0:
                raise ValueError("constant damage must be >= 0")
            return cls(0, 0, value)
        text = str(value).replace(" ", "")
        if text.isdigit():
            return cls(0, 0, int(text))
        match = _DICE_RE.match(text)
        if not match:
            raise ValueError(f"invalid dice expression {value!r}")
        count = int(match[1]) if match[1] else 1
        sides = int(match[2])
        const = int(match[4]) * (-1 if match[3] == "-" else 1) if match[3] else 0
        if not 1 <= count <= MAX_DICE or sides < 2:
            raise ValueError(f"invalid dice expression {value!r}")
        return cls(count, sides, const)

    @property
    def minimum(self) -> int:
        return self.count + self.const

    @property
    def maximum(self) -> int:
        return self.count * self.sides + self.const

    @property
    def mean(self) -> Fraction:
        return Fraction(self.count * (self.sides + 1), 2) + self.const

    def __str__(self) -> str:
        if self.count == 0:
            return str(self.const)
        dice = f"{self.count if self.count > 1 else ''}D{self.sides}"
        if self.const > 0:
            return f"{dice}+{self.const}"
        if self.const < 0:
            return f"{dice}{self.const}"
        return dice
