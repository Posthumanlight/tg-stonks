"""The `/ws` endpoint: handshake, read loop, close codes (docs/protocol.md "WebSocket")."""

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.auth.tokens import LEEWAY_S
from app.protocol import PROTOCOL_VERSION, ws
from app.shared.clock import Clock
from app.shared.dispatch import UnknownMessage
from app.shared.errors import GameError
from app.ws.connection import CloseCode, Connection
from app.ws.router import WsContext, dispatcher

log = logging.getLogger(__name__)
router = APIRouter()

HANDSHAKE_TIMEOUT_S = 5.0
IDLE_TIMEOUT_S = 60.0
WATCHDOG_INTERVAL_S = 0.5


def _error(reason_key: str, request_id: str | None = None) -> dict:
    return ws.ErrorMessage(
        type="error", id=request_id, payload=ws.ErrorPayload(reason_key=reason_key)
    ).model_dump(mode="json")


async def _handshake(websocket: WebSocket) -> ws.HelloMessage | CloseCode:
    try:
        text = await asyncio.wait_for(websocket.receive_text(), HANDSHAKE_TIMEOUT_S)
    except asyncio.TimeoutError:
        return CloseCode.HANDSHAKE_TIMEOUT
    try:
        message = ws.CLIENT_MESSAGE.validate_json(text)
    except ValidationError:
        return CloseCode.BAD_MESSAGE
    if not isinstance(message, ws.HelloMessage):
        return CloseCode.BAD_MESSAGE
    if message.payload.protocol_version != PROTOCOL_VERSION:
        await websocket.send_json(_error("protocol.version_mismatch"))
        return CloseCode.PROTOCOL_MISMATCH
    return message


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    state = websocket.app.state
    clock: Clock = state.clock
    hello = await _handshake(websocket)
    if isinstance(hello, CloseCode):
        await websocket.close(hello)
        return
    try:
        principal = state.auth.tokens.verify(hello.payload.access_token)
    except GameError:
        await websocket.close(CloseCode.UNAUTHORIZED)
        return

    connection = Connection(websocket, principal, clock)
    context = WsContext(connection, state.auth.tokens, state.combat_router, state.rooms)
    connection.start()
    connection.send(
        ws.WelcomeMessage(
            type="welcome",
            payload=ws.WelcomePayload(
                user_id=principal.user_id,
                role=principal.role,
                protocol_version=PROTOCOL_VERSION,
            ),
        ).model_dump(mode="json")
    )
    watchdog: Watchdog = state.ws_watchdog
    watchdog.add(connection)
    try:
        await _read_loop(websocket, connection, context)
    except WebSocketDisconnect:
        pass
    finally:
        watchdog.remove(connection)
        state.combat_router.drop(connection)
        state.rooms.drop(connection)
        await connection.stop()
        if connection.close_code is not None:
            with contextlib.suppress(Exception):
                await websocket.close(connection.close_code)


async def _read_loop(
    websocket: WebSocket, connection: Connection, context: WsContext
) -> None:
    # One long-lived "closing" waiter for the whole connection (not one per message).
    closing = asyncio.ensure_future(connection.closing.wait())
    try:
        while connection.close_code is None:
            receive = asyncio.ensure_future(websocket.receive_text())
            await asyncio.wait({receive, closing}, return_when=asyncio.FIRST_COMPLETED)
            if not receive.done():
                receive.cancel()
                return  # the watchdog or a full queue asked us to close
            if not await _handle(receive.result(), connection, context):
                return
    finally:
        closing.cancel()


async def _handle(text: str, connection: Connection, context: WsContext) -> bool:
    """Process one client frame. False when the connection must close."""
    if not connection.received():
        connection.close(CloseCode.RATE_LIMITED)
        return False
    try:
        message = ws.CLIENT_MESSAGE.validate_json(text)
    except ValidationError:
        connection.close(CloseCode.BAD_MESSAGE)
        return False
    await _dispatch(connection, context, message)
    return connection.close_code is None


async def _dispatch(
    connection: Connection, context: WsContext, message
) -> None:  # noqa: ANN001
    request_id = getattr(message, "id", None)
    try:
        if isinstance(message, ws.HelloMessage):
            raise GameError("ws.already_authenticated", 400)
        await dispatcher.dispatch(message.type, context, message)
    except GameError as exc:
        connection.send(_error(exc.reason_key, request_id))
        return
    except UnknownMessage:
        connection.close(CloseCode.BAD_MESSAGE)
        return
    except Exception:
        log.exception("ws handler %s failed", message.type)
        connection.send(_error("combat.internal", request_id))
        return
    if request_id is not None and not isinstance(message, ws.PingMessage):
        connection.send(
            ws.AckMessage(type="ack", id=request_id).model_dump(mode="json")
        )


class Watchdog:
    """One task for all connections: close on token expiry (no `auth.refresh` in time)
    or silence. Cheaper than a timer task per socket at 1k connections."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._connections: set[Connection] = set()

    def add(self, connection: Connection) -> None:
        self._connections.add(connection)

    def remove(self, connection: Connection) -> None:
        self._connections.discard(connection)

    def check(self) -> None:
        now, monotonic = self._clock.now(), self._clock.monotonic()
        for connection in list(self._connections):
            if connection.close_code is not None:
                continue
            if now > connection.principal.expires_at + LEEWAY_S:
                connection.close(CloseCode.UNAUTHORIZED)
            elif monotonic - connection.last_seen > IDLE_TIMEOUT_S:
                connection.close(CloseCode.GOING_AWAY)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL_S)  # read each time: tests shorten it
            self.check()
