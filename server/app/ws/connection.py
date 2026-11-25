"""One client connection: bounded outbound queue + writer task, rate limit, liveness.

Implements the router's `Subscriber` (`push_combat_update`), so services push to it
without knowing about WebSockets.
"""

import asyncio
import contextlib
import json
from enum import IntEnum
from typing import Any

from starlette.websockets import WebSocket

from app.auth.tokens import Principal
from app.shared.clock import Clock
from app.shared.ratelimit import TokenBucket

QUEUE_SIZE = 256
RATE_PER_S = 20
BURST = 40


class CloseCode(IntEnum):
    BAD_MESSAGE = 4400
    UNAUTHORIZED = 4401
    HANDSHAKE_TIMEOUT = 4408
    PROTOCOL_MISMATCH = 4426
    RATE_LIMITED = 4429
    GOING_AWAY = 1001  # idle: no message for too long
    SERVER_ERROR = 1011  # incl. outbound queue overflow


class Connection:
    def __init__(
        self, websocket: WebSocket, principal: Principal, clock: Clock
    ) -> None:
        self.websocket = websocket
        self.principal = principal
        self._clock = clock
        self.bucket = TokenBucket(RATE_PER_S, BURST, clock)
        self.last_seen = clock.monotonic()
        # Ready-to-send frames (JSON text); None stops the writer.
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(QUEUE_SIZE)
        self.close_code: CloseCode | None = None
        self.closing = asyncio.Event()  # set when the connection should close
        self._writer: asyncio.Task[None] | None = None

    @property
    def user_id(self) -> int:
        return self.principal.user_id

    # --- outbound ----------------------------------------------------------------------

    def start(self) -> None:
        self._writer = asyncio.create_task(self._write_loop())

    def send(self, message: dict[str, Any]) -> None:
        """Queue a message. A client that can't keep up is disconnected (it resyncs)."""
        self._enqueue(json.dumps(message, separators=(",", ":")))

    def push_combat_update(self, combat_id: str, update_json: str) -> None:
        # The update arrives serialized from the worker: splice, don't re-encode.
        self._enqueue('{"type":"combat.events","payload":' + update_json + "}")

    def _enqueue(self, frame: str) -> None:
        if self.close_code is not None:
            return
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            self.close(CloseCode.SERVER_ERROR)

    def close(self, code: CloseCode) -> None:
        """Ask the connection to close (the gateway's read loop notices)."""
        if self.close_code is None:
            self.close_code = code
            self.closing.set()

    async def _write_loop(self) -> None:
        while True:
            frame = await self._queue.get()
            if frame is None:
                break
            await self.websocket.send_text(frame)

    async def stop(self) -> None:
        """Stop the writer after flushing what's queued (best effort)."""
        if self._writer is None:
            return
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(None)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._writer, 2)
        self._writer.cancel()

    # --- inbound -----------------------------------------------------------------------

    def received(self) -> bool:
        """Account one incoming message. False when the client exceeded its rate."""
        self.last_seen = self._clock.monotonic()
        return self.bucket.take()
