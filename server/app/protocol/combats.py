"""Combat HTTP bodies (docs/protocol.md "HTTP endpoints")."""

from app.protocol.base import ProtocolModel


class CombatCreated(ProtocolModel):
    combat_id: str


class CombatSummaryView(ProtocolModel):
    combat_id: str
    mode: str
    status: str  # active | finished | abandoned | aborted
    created_at: str  # ISO 8601
