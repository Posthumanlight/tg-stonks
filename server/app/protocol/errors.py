"""Structured error details (docs/protocol.md "HTTP endpoints")."""

from app.protocol.base import ProtocolModel


class SetupErrorRef(ProtocolModel):
    """`detail` of a `setup.*` error: which side, and which unit in it (null for
    side-wide errors)."""

    side: int | None
    unit: int | None
