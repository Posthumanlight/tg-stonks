from typing import Literal

from app.protocol.base import ProtocolModel


class HealthView(ProtocolModel):
    """`GET /api/health`."""

    status: Literal["ok"]
    protocol_version: int
