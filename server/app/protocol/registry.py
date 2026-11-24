"""Models exported to the client by `npm run gen:protocol` (app/cli/export_schema.py)."""

from pydantic import BaseModel

from app.protocol.auth import (
    ErrorBody,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserView,
)
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
)
