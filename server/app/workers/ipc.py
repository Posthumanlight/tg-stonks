"""Gateway ↔ worker IPC: length-prefixed JSON frames over asyncio streams.

Internal only — not part of the client protocol, no TypeScript codegen
(docs/architecture.md "Internal IPC").
"""

import asyncio
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

MAX_FRAME = 16 * 1024 * 1024
HEADER = 4


class _Msg(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# gateway → worker


class HelloAck(_Msg):
    type: Literal["hello_ack"] = "hello_ack"


class Create(_Msg):
    type: Literal["create"] = "create"
    request_id: int
    combat_id: str
    owner_user_id: int
    mode: str
    setup: dict[str, Any]


class Intent(_Msg):
    type: Literal["intent"] = "intent"
    request_id: int
    combat_id: str
    user_id: int
    intent: dict[str, Any]


class Subscribe(_Msg):
    type: Literal["subscribe"] = "subscribe"
    request_id: int
    combat_id: str
    user_id: int
    last_seq: int | None = None


class Close(_Msg):
    """The owner abandoned the combat: flush, mark it `abandoned`, drop it."""

    type: Literal["close"] = "close"
    request_id: int
    combat_id: str
    reason: str


class Ping(_Msg):
    type: Literal["ping"] = "ping"


class Drain(_Msg):
    type: Literal["drain"] = "drain"


# worker → gateway


class Hello(_Msg):
    type: Literal["hello"] = "hello"
    slot: int
    boot_token: str


class Reply(_Msg):
    type: Literal["reply"] = "reply"
    request_id: int
    ok: bool
    payload: dict[str, Any] | None = None
    reason_key: str | None = None
    status: int = 200


class Pushed(_Msg):
    type: Literal["pushed"] = "pushed"
    combat_id: str
    update: str  # CombatUpdate JSON text: the gateway forwards it unparsed


class LoadReport(_Msg):
    type: Literal["load_report"] = "load_report"
    instances: int


class Pong(_Msg):
    type: Literal["pong"] = "pong"


Message = Annotated[
    HelloAck
    | Create
    | Intent
    | Subscribe
    | Close
    | Ping
    | Drain
    | Hello
    | Reply
    | Pushed
    | LoadReport
    | Pong,
    Field(discriminator="type"),
]
_ADAPTER: TypeAdapter[Message] = TypeAdapter(Message)


def encode(message: _Msg) -> bytes:
    body = message.model_dump_json().encode()
    if len(body) > MAX_FRAME:
        raise ValueError("IPC frame too large")
    return len(body).to_bytes(HEADER, "big") + body


def decode(body: bytes) -> Message:
    return _ADAPTER.validate_json(body)


class IpcChannel:
    """One framed connection. `write` is synchronous and ordered; `drain` flushes."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._reader = reader
        self._writer = writer

    def write(self, message: _Msg) -> None:
        self._writer.write(encode(message))

    async def drain(self) -> None:
        await self._writer.drain()

    async def send(self, message: _Msg) -> None:
        self.write(message)
        await self.drain()

    async def recv(self) -> Message:
        """Raises asyncio.IncompleteReadError when the peer closes."""
        size = int.from_bytes(await self._reader.readexactly(HEADER), "big")
        if size > MAX_FRAME:
            raise ValueError("IPC frame too large")
        return decode(await self._reader.readexactly(size))

    def close(self) -> None:
        self._writer.close()
