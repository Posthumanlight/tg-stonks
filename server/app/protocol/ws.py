"""WebSocket messages (docs/protocol.md "WebSocket"). Envelope: `{type, id?, payload}`.

Client messages are validated as one discriminated union. Server messages are typed
here for codegen; pushes built from worker JSON are forwarded without re-validation.
"""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from app.protocol.base import ProtocolModel
from app.protocol.combat import CombatIntent, CombatSnapshot, CombatUpdate

RequestId = Annotated[str, Field(max_length=64)]


# --- client → server -------------------------------------------------------------------


class HelloPayload(ProtocolModel):
    protocol_version: int
    access_token: str = Field(max_length=4096)


class HelloMessage(ProtocolModel):
    type: Literal["hello"]
    id: RequestId | None = None
    payload: HelloPayload


class AuthRefreshPayload(ProtocolModel):
    access_token: str = Field(max_length=4096)


class AuthRefreshMessage(ProtocolModel):
    type: Literal["auth.refresh"]
    id: RequestId | None = None
    payload: AuthRefreshPayload


class PingMessage(ProtocolModel):
    type: Literal["ping"]
    id: RequestId | None = None


class SubscribePayload(ProtocolModel):
    combat_id: str = Field(max_length=64)
    last_seq: int | None = Field(default=None, ge=0)


class SubscribeMessage(ProtocolModel):
    type: Literal["combat.subscribe"]
    id: RequestId | None = None
    payload: SubscribePayload


class UnsubscribePayload(ProtocolModel):
    combat_id: str = Field(max_length=64)


class UnsubscribeMessage(ProtocolModel):
    type: Literal["combat.unsubscribe"]
    id: RequestId | None = None
    payload: UnsubscribePayload


class ActionPayload(ProtocolModel):
    combat_id: str = Field(max_length=64)
    intent: CombatIntent = Field(discriminator="type")


class ActionMessage(ProtocolModel):
    type: Literal["combat.action"]
    id: RequestId | None = None
    payload: ActionPayload


ClientMessage = Annotated[
    HelloMessage
    | AuthRefreshMessage
    | PingMessage
    | SubscribeMessage
    | UnsubscribeMessage
    | ActionMessage,
    Field(discriminator="type"),
]
CLIENT_MESSAGE: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


# --- server → client -------------------------------------------------------------------


class WelcomePayload(ProtocolModel):
    user_id: int
    role: str
    protocol_version: int


class WelcomeMessage(ProtocolModel):
    type: Literal["welcome"]
    payload: WelcomePayload


class AckMessage(ProtocolModel):
    type: Literal["ack"]
    id: str


class ErrorPayload(ProtocolModel):
    reason_key: str
    detail: str | None = None


class ErrorMessage(ProtocolModel):
    type: Literal["error"]
    id: str | None = None
    payload: ErrorPayload


class PongMessage(ProtocolModel):
    type: Literal["pong"]
    id: str | None = None


class CombatSnapshotMessage(ProtocolModel):
    type: Literal["combat.snapshot"]
    payload: CombatSnapshot


class CombatEventsMessage(ProtocolModel):
    type: Literal["combat.events"]
    payload: CombatUpdate


SERVER_MESSAGES = (
    WelcomeMessage,
    AckMessage,
    ErrorMessage,
    PongMessage,
    CombatSnapshotMessage,
    CombatEventsMessage,
)
CLIENT_MESSAGES = (
    HelloMessage,
    AuthRefreshMessage,
    PingMessage,
    SubscribeMessage,
    UnsubscribeMessage,
    ActionMessage,
)
