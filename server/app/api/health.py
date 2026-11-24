from fastapi import APIRouter

from app.protocol import PROTOCOL_VERSION
from app.protocol.health import HealthView

router = APIRouter()


@router.get("/health")
async def health() -> HealthView:
    return HealthView(status="ok", protocol_version=PROTOCOL_VERSION)
