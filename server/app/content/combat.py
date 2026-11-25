"""Schemas and loader for `content/combat/**.toml` (see docs/combat-ground.md).

This module validates the *data*. Binding abilities to registered Python functions (and
checking their parameters) happens in `app.combat.ground.ruleset.compile_ruleset`.
"""

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    PlainValidator,
    model_validator,
)

from app.combat.ground.dice import Dice
from app.config import REPO_ROOT

DEFAULT_CONTENT_DIR = REPO_ROOT / "content" / "combat"

ARMOR_TYPES: tuple[str, ...] = ("light", "heavy", "vehicle", "monster", "character")
Armor = Literal["light", "heavy", "vehicle", "monster", "character"]
CoverKind = Literal["none", "obstacle", "area"]
LosProfile = Literal["none", "screen", "block"]
AbilityKind = Literal["weapon", "passive", "active", "status"]
Scope = Literal["weapon", "self", "self_target", "ally", "enemy", "any"]
ParamType = Literal[
    "integer",
    "boolean",
    "dice",
    "armor",
    "tag",
    "status",
    "terrain",
    "overlay",
    "unit_type",
    "weapon_type",
]

DiceField = Annotated[Dice, PlainValidator(Dice.parse), PlainSerializer(str)]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- rules.toml ------------------------------------------------------------------------


class BoardSize(_Model):
    width: int = Field(ge=1)
    height: int = Field(ge=1)


class RulesContent(_Model):
    default_board: BoardSize
    board_min: int = Field(ge=1)
    board_max: int = Field(ge=1)
    round_limit: int = Field(ge=1)
    draw_margin_percent: int = Field(ge=0, le=100)
    activation_timer_s: int = Field(ge=1)
    max_models_per_unit: int = Field(ge=1)
    base_reactions: int = Field(ge=0)
    opportunity_attack_hit_percent: int = Field(ge=0)
    friendly_units_screen: bool
    first_round_no_attacks: bool
    max_trigger_depth: int = Field(ge=1)

    @model_validator(mode="after")
    def _board_limits(self) -> "RulesContent":
        if self.board_min > self.board_max:
            raise ValueError("board_min exceeds board_max")
        for side in (self.default_board.width, self.default_board.height):
            if not self.board_min <= side <= self.board_max:
                raise ValueError("default_board must be within board_min..board_max")
        return self


# --- terrain.toml ----------------------------------------------------------------------


class TerrainType(_Model):
    name_key: str
    passable: bool
    move_cost: int = Field(default=1, ge=1)
    blocks_los: bool = False
    cover: CoverKind = "none"


class OverlayType(_Model):
    """A temporary layer; only the fields it sets override the terrain underneath."""

    name_key: str
    passable: bool | None = None
    move_cost: int | None = Field(default=None, ge=1)
    blocks_los: bool | None = None
    cover: CoverKind | None = None


# --- weapons / units / abilities -------------------------------------------------------


class WeaponTypeDef(_Model):
    name_key: str


class AbilityRef(_Model):
    """`"heavy"` or `{ id = "anti", armor = "vehicle", percent = 150 }`."""

    id: str
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"id": data, "params": {}}
        if isinstance(data, dict) and "params" not in data:
            rest = {k: v for k, v in data.items() if k != "id"}
            return {"id": data.get("id"), "params": rest}
        return data


class Weapon(_Model):
    name_key: str
    mode: Literal["melee", "ranged"]
    type: str
    range: tuple[int, int] = (1, 1)
    hits: int = Field(ge=1)
    damage: DiceField
    ap_cost: int = Field(default=1, ge=0)
    abilities: tuple[AbilityRef, ...] = ()

    @model_validator(mode="after")
    def _range(self) -> "Weapon":
        low, high = self.range
        if not 1 <= low <= high:
            raise ValueError("range must be [min, max] with 1 <= min <= max")
        if self.mode == "melee" and self.range != (1, 1):
            raise ValueError("melee weapons have range [1, 1]; use `reach` to extend")
        return self


class Group(_Model):
    role: str
    count: int = Field(ge=0)
    fill: bool = False
    weapons: tuple[str, ...] = Field(min_length=1)
    hp: int | None = Field(default=None, ge=1)
    casualty_priority: int = 0


class ModelsRange(_Model):
    min: int = Field(ge=1)
    max: int = Field(ge=1)


class Unit(_Model):
    name_key: str
    points: int = Field(ge=0)
    speed: int = Field(ge=0)
    movement: int = Field(ge=0)
    hp: int = Field(ge=1)
    armor: Armor
    tags: tuple[str, ...] = ()
    action_points: int = Field(ge=0)
    footprint: Literal[1, 2]
    models: ModelsRange
    los_profile: LosProfile | None = None
    abilities: tuple[AbilityRef, ...] = ()
    groups: tuple[Group, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _groups(self) -> "Unit":
        if self.models.min > self.models.max:
            raise ValueError("models.min exceeds models.max")
        if sum(g.fill for g in self.groups) != 1:
            raise ValueError("exactly one group must have fill = true")
        roles = [g.role for g in self.groups]
        if len(set(roles)) != len(roles):
            raise ValueError("group roles must be unique")
        if not self.models.min <= self.default_models <= self.models.max:
            raise ValueError("sum of group counts must be within models.min..max")
        return self

    @property
    def default_models(self) -> int:
        return sum(g.count for g in self.groups)

    @property
    def default_los_profile(self) -> str:
        if self.los_profile is not None:
            return self.los_profile
        big = self.footprint == 2 or self.armor in ("vehicle", "monster")
        return "block" if big else "screen"


class FnCall(_Model):
    """`{ fn = "multiply_damage", percent = 150 }` -> fn + args."""

    fn: str
    args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _split(cls, data: Any) -> Any:
        if isinstance(data, dict) and "args" not in data:
            return {
                "fn": data.get("fn"),
                "args": {k: v for k, v in data.items() if k != "fn"},
            }
        return data


class Trigger(_Model):
    event: str
    scope: Scope | None = None
    conditions: tuple[FnCall, ...] = ()
    actions: tuple[FnCall, ...] = Field(min_length=1)
    priority: int = 0


class Targeting(_Model):
    type: Literal["self", "ally", "enemy", "unit", "square"]
    range: int = Field(default=0, ge=0)
    los: bool = False
    radius: int = Field(default=0, ge=0)  # informational, for the client's preview


class Ability(_Model):
    name_key: str
    description_key: str | None = None
    kind: AbilityKind
    params: dict[str, ParamType] = Field(default_factory=dict)
    triggers: tuple[Trigger, ...] = ()
    # active only
    ap_cost: int = Field(default=1, ge=0)
    cooldown: int = Field(default=0, ge=0)
    uses: int | None = Field(default=None, ge=1)
    targeting: Targeting | None = None
    on_cast: tuple[FnCall, ...] = ()
    # status only
    duration: int | None = Field(default=None, ge=1)
    stacking: Literal["refresh", "stack", "ignore"] = "refresh"
    max_stacks: int = Field(default=1, ge=1)
    los_profile: LosProfile | None = None

    @model_validator(mode="after")
    def _kind_fields(self) -> "Ability":
        if self.kind == "active":
            if self.targeting is None or not self.on_cast:
                raise ValueError("active abilities need `targeting` and `on_cast`")
        elif self.targeting is not None or self.on_cast:
            raise ValueError("only active abilities have `targeting` / `on_cast`")
        if self.kind == "status":
            if self.duration is None:
                raise ValueError("status abilities need `duration`")
            if self.params:
                raise ValueError("status abilities can't take params")
        elif self.duration is not None or self.los_profile is not None:
            raise ValueError("only status abilities have `duration` / `los_profile`")
        return self


# --- all together ----------------------------------------------------------------------


class CombatContent(_Model):
    rules: RulesContent
    terrain: dict[str, TerrainType] = Field(min_length=1)
    overlays: dict[str, OverlayType] = Field(default_factory=dict)
    tags: tuple[str, ...]
    weapon_types: dict[str, WeaponTypeDef] = Field(min_length=1)
    damage_table: dict[str, dict[Armor, int]]
    weapons: dict[str, Weapon]
    units: dict[str, Unit]
    abilities: dict[str, Ability]

    @model_validator(mode="after")
    def _cross_checks(self) -> "CombatContent":
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("duplicate tags")
        if set(self.damage_table) != set(self.weapon_types):
            raise ValueError("damage_table rows must match weapon_types exactly")
        for wtype, row in self.damage_table.items():
            if set(row) != set(ARMOR_TYPES) or min(row.values()) < 0:
                raise ValueError(
                    f"damage_table.{wtype}: need a value >= 0 per armor type"
                )
        for wid, weapon in self.weapons.items():
            if weapon.type not in self.weapon_types:
                raise ValueError(f"weapon {wid!r}: unknown type {weapon.type!r}")
            self._check_refs(f"weapon {wid!r}", weapon.abilities, {"weapon"})
        for uid, unit in self.units.items():
            if unknown := set(unit.tags) - set(self.tags):
                raise ValueError(f"unit {uid!r}: unknown tags {sorted(unknown)}")
            if unit.models.max > self.rules.max_models_per_unit:
                raise ValueError(
                    f"unit {uid!r}: models.max exceeds max_models_per_unit"
                )
            for group in unit.groups:
                if unknown := set(group.weapons) - set(self.weapons):
                    raise ValueError(f"unit {uid!r}: unknown weapons {sorted(unknown)}")
            self._check_refs(f"unit {uid!r}", unit.abilities, {"passive", "active"})
        return self

    def _check_refs(
        self, where: str, refs: tuple[AbilityRef, ...], kinds: set[str]
    ) -> None:
        for ref in refs:
            ability = self.abilities.get(ref.id)
            if ability is None:
                raise ValueError(f"{where}: unknown ability {ref.id!r}")
            if ability.kind not in kinds:
                raise ValueError(f"{where}: ability {ref.id!r} is {ability.kind!r}")

    def status_ids(self) -> set[str]:
        return {aid for aid, a in self.abilities.items() if a.kind == "status"}


# --- loading ---------------------------------------------------------------------------

TOP_LEVEL_FILES = (
    "rules",
    "terrain",
    "tags",
    "weapon_types",
    "damage_table",
    "weapons",
    "units",
)


def load_raw_combat_content(directory: Path = DEFAULT_CONTENT_DIR) -> dict[str, Any]:
    """Read all TOML files into one dict shaped like `CombatContent`."""
    files: dict[str, Any] = {}
    for name in TOP_LEVEL_FILES:
        with open(directory / f"{name}.toml", "rb") as f:
            files[name] = tomllib.load(f)
    abilities: dict[str, Any] = {}
    for path in sorted((directory / "abilities").glob("*.toml")):
        with open(path, "rb") as f:
            for aid, ability in tomllib.load(f).get("abilities", {}).items():
                if aid in abilities:
                    raise ValueError(f"ability {aid!r} defined twice ({path.name})")
                abilities[aid] = ability
    return {
        "rules": files["rules"],
        "terrain": files["terrain"].get("terrain", {}),
        "overlays": files["terrain"].get("overlays", {}),
        "tags": files["tags"].get("tags", []),
        "weapon_types": files["weapon_types"].get("weapon_types", {}),
        "damage_table": files["damage_table"].get("damage_table", {}),
        "weapons": files["weapons"].get("weapons", {}),
        "units": files["units"].get("units", {}),
        "abilities": abilities,
    }


def content_hash(raw: dict[str, Any]) -> str:
    """Stable hash of the raw content; recorded with every combat (replays need it)."""
    data = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode()).hexdigest()


class DemoUnit(_Model):
    type: str
    side: int = Field(ge=0)
    origin: tuple[int, int]
    models: int | None = Field(default=None, ge=1)


class DemoBattle(_Model):
    """`content/combat/demo.toml`: the fixed hotseat demo (board rows + armies)."""

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    legend: dict[str, str]
    rows: tuple[str, ...]
    units: tuple[DemoUnit, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _shape(self) -> "DemoBattle":
        if len(self.rows) != self.height or any(
            len(r) != self.width for r in self.rows
        ):
            raise ValueError("rows must be `height` strings of `width` characters")
        if any(len(key) != 1 for key in self.legend):
            raise ValueError("legend keys must be single characters")
        return self


def parse_combat_content(raw: dict[str, Any]) -> CombatContent:
    return CombatContent.model_validate(raw)
