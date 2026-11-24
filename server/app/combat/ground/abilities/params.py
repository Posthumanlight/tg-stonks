"""Typed parameters for ability functions, validated against content at startup.

Content-id types check membership using the validation context
`{"content": CombatContent}` passed by the ruleset compiler.
"""

from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    PlainValidator,
    ValidationInfo,
)

from app.combat.ground.dice import Dice


class Params(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NoParams(Params):
    pass


def _ids(kind: str) -> Any:
    def check(value: str, info: ValidationInfo) -> str:
        content = (info.context or {}).get("content")
        if content is None:
            return value
        if kind == "armor":
            from app.content.combat import ARMOR_TYPES

            known: Any = ARMOR_TYPES
        elif kind == "tag":
            known = content.tags
        elif kind == "status":
            known = content.status_ids()
        else:
            known = getattr(content, kind)
        if value not in known:
            raise ValueError(f"unknown {kind} {value!r}")
        return value

    return AfterValidator(check)


ArmorId = Annotated[str, _ids("armor")]
TagId = Annotated[str, _ids("tag")]
StatusId = Annotated[str, _ids("status")]
TerrainId = Annotated[str, _ids("terrain")]
OverlayId = Annotated[str, _ids("overlays")]
UnitTypeId = Annotated[str, _ids("units")]
WeaponTypeId = Annotated[str, _ids("weapon_types")]
DiceParam = Annotated[Dice, PlainValidator(Dice.parse)]
StatName = Literal["speed", "movement", "action_points", "reactions"]
