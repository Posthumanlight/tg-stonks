"""Custom battle bodies (docs/protocol.md "Custom battle models") and their pure
converters to and from the engine's deployment types."""

from pydantic import Field

from app.combat.ground.deployment import Army, ArmyUnit, BattleMap
from app.combat.ground.ruleset import CombatRuleset
from app.combat.ground.setup import Zone
from app.protocol.base import ProtocolModel
from app.protocol.combat import BoardView
from app.protocol.errors import SetupErrorRef  # noqa: F401 - re-exported

Pair = tuple[int, int]
RectTuple = tuple[int, int, int, int]  # x, y, w, h

# A hard cap on the request's size, before any content rule runs. The content cap
# (`rules.max_units_per_side`) is lower and gives a proper `setup.too_many_units`.
MAX_UNITS_IN_REQUEST = 64


class TerrainCard(ProtocolModel):
    passable: bool


class DeployZone(ProtocolModel):
    side: int
    rects: list[RectTuple]


class ModelRange(ProtocolModel):
    min: int
    max: int
    default: int


class UnitCard(ProtocolModel):
    unit_type: str
    name_key: str
    points: int
    footprint: int  # 1 or 2 (squares per side)
    models: ModelRange


class FactionCard(ProtocolModel):
    id: str
    name_key: str
    units: list[UnitCard]


class BuilderLimits(ProtocolModel):
    max_units_per_side: int


class RoomPresets(ProtocolModel):
    """What a host may choose for an online room, and where each side deploys."""

    points_presets: list[int]  # 0 = unlimited
    timer_presets: list[int]  # seconds per activation; 0 = unlimited
    default_timer_s: int
    zones: list[DeployZone] | None  # null: the whole board


class DeployedUnit(ProtocolModel):
    unit_type: str
    models: int = Field(ge=1)
    origin: Pair  # the footprint's top-left square


class SideSetup(ProtocolModel):
    faction: str
    units: list[DeployedUnit] = Field(max_length=MAX_UNITS_IN_REQUEST)


class CustomCombatRequest(ProtocolModel):
    sides: list[SideSetup] = Field(min_length=2, max_length=2)  # side = list index


class BuilderView(ProtocolModel):
    board: BoardView  # `factions` is null here: the request picks them
    terrain: dict[str, TerrainCard]
    zones: list[DeployZone] | None  # null: the whole board is allowed
    factions: list[FactionCard]
    limits: BuilderLimits
    defaults: CustomCombatRequest
    rooms: RoomPresets


# --- converters (pure) -----------------------------------------------------------------


def army_from_side(side: SideSetup) -> Army:
    return Army(
        side.faction,
        tuple(ArmyUnit(u.unit_type, u.origin, u.models) for u in side.units),
    )


def request_side(army: Army) -> SideSetup:
    """An army whose model counts are all set (a player's) back as a request side."""
    return SideSetup(
        faction=army.faction,
        units=[
            DeployedUnit(unit_type=u.unit_type, models=u.models, origin=u.origin)
            for u in army.units
        ],
    )


def armies_from_request(request: CustomCombatRequest) -> tuple[Army, ...]:
    return tuple(army_from_side(side) for side in request.sides)


def request_from_armies(
    ruleset: CombatRuleset, armies: tuple[Army, ...]
) -> CustomCombatRequest:
    units = ruleset.content.units
    return CustomCombatRequest(
        sides=[
            SideSetup(
                faction=army.faction,
                units=[
                    DeployedUnit(
                        unit_type=u.unit_type,
                        models=u.models or units[u.unit_type].default_models,
                        origin=u.origin,
                    )
                    for u in army.units
                ],
            )
            for army in armies
        ]
    )


def _zones(zones: tuple[Zone, ...] | None) -> list[DeployZone] | None:
    if zones is None:
        return None
    return [
        DeployZone(side=z.side, rects=[(r.x, r.y, r.w, r.h) for r in z.rects])
        for z in zones
    ]


def builder_view(
    ruleset: CombatRuleset, battle_map: BattleMap, room_map: BattleMap
) -> BuilderView:
    """`battle_map` is the hotseat builder's (no zones); `room_map` adds the zones
    online rooms deploy in."""
    content = ruleset.content
    pvp = ruleset.rules.pvp
    board = battle_map.board
    return BuilderView(
        board=BoardView(
            width=board.width, height=board.height, terrain=list(board.terrain)
        ),
        terrain={
            tid: TerrainCard(passable=passable)
            for tid, passable in ruleset.passable_terrain.items()
        },
        zones=_zones(battle_map.zones),
        factions=[
            FactionCard(
                id=fid,
                name_key=faction.name_key,
                units=[
                    UnitCard(
                        unit_type=uid,
                        name_key=unit.name_key,
                        points=unit.points,
                        footprint=unit.footprint,
                        models=ModelRange(
                            min=unit.models.min,
                            max=unit.models.max,
                            default=unit.default_models,
                        ),
                    )
                    for uid, unit in content.units.items()
                    if unit.faction == fid
                ],
            )
            for fid, faction in content.factions.items()
        ],
        limits=BuilderLimits(max_units_per_side=ruleset.rules.max_units_per_side),
        defaults=request_from_armies(ruleset, battle_map.defaults),
        rooms=RoomPresets(
            points_presets=list(pvp.points_presets),
            timer_presets=list(pvp.timer_presets),
            default_timer_s=ruleset.rules.activation_timer_s,
            zones=_zones(room_map.zones),
        ),
    )
