"""Models exported to the client by `npm run gen:protocol` (app/cli/export_schema.py)."""

from pydantic import BaseModel

from app.protocol import builder, combat, ws
from app.protocol.auth import (
    ErrorBody,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserView,
)
from app.protocol.combats import CombatCreated, CombatSummaryView
from app.protocol.health import HealthView
from app.protocol.world import ClusterView, GalaxyView, LinkView, StarView

PROTOCOL_MODELS: tuple[type[BaseModel], ...] = (
    HealthView,
    ErrorBody,
    RegisterRequest,
    LoginRequest,
    UserView,
    TokenResponse,
    ClusterView,
    StarView,
    LinkView,
    GalaxyView,
    CombatCreated,
    CombatSummaryView,
    builder.BuilderView,
    builder.CustomCombatRequest,
    combat.CombatSnapshot,
    combat.CombatUpdate,
    combat.MoveIntent,
    combat.AttackIntent,
    combat.AbilityIntent,
    combat.WaitIntent,
    combat.SkipIntent,
    *ws.CLIENT_MESSAGES,
    *ws.SERVER_MESSAGES,
)
