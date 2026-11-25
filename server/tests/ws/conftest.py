"""A live uvicorn server in the test's event loop, plus a small WebSocket test client."""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import ClientConnection, connect

from app.protocol import PROTOCOL_VERSION
from app.shared.clock import FakeClock
from app.ws import gateway

from tests.conftest import built_app


@dataclass
class Live:
    http: httpx.AsyncClient
    ws_url: str
    clock: FakeClock
    app: Any

    async def token(self, username: str = "alice") -> str:
        body = {"username": username, "password": "correct horse"}
        await self.http.post("/api/auth/register", json=body)
        response = await self.http.post("/api/auth/login", json=body)
        return response.json()["access_token"]

    async def demo(self, token: str) -> str:
        response = await self.http.post(
            "/api/combats/demo", headers={"Authorization": f"Bearer {token}"}
        )
        return response.json()["combat_id"]


@pytest.fixture
async def live(tmp_path: Path, monkeypatch) -> AsyncIterator[Live]:
    monkeypatch.setattr(gateway, "HANDSHAKE_TIMEOUT_S", 0.3)
    monkeypatch.setattr(gateway, "WATCHDOG_INTERVAL_S", 0.02)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    async with built_app(tmp_path) as (app, clock, _):
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        while not server.started:
            await asyncio.sleep(0.01)
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(base_url=base) as http:
            yield Live(http, f"ws://127.0.0.1:{port}/ws", clock, app)
        server.should_exit = True
        await task


class WsClient:
    def __init__(self, connection: ClientConnection) -> None:
        self.connection = connection
        self._ids = 0

    async def send(
        self, type_: str, payload: dict | None = None, *, with_id: bool = True
    ) -> str | None:
        message: dict[str, Any] = {"type": type_}
        request_id = None
        if with_id:
            self._ids += 1
            request_id = message["id"] = f"r{self._ids}"
        if payload is not None:
            message["payload"] = payload
        await self.connection.send(json.dumps(message))
        return request_id

    async def recv(self, timeout: float = 3.0) -> dict:
        return json.loads(await asyncio.wait_for(self.connection.recv(), timeout))

    async def recv_until(
        self, type_: str, timeout: float = 3.0
    ) -> tuple[dict, list[dict]]:
        """The first message of `type_`, and everything received before it."""
        skipped = []
        while True:
            message = await self.recv(timeout)
            if message["type"] == type_:
                return message, skipped
            skipped.append(message)

    async def close_code(self, timeout: float = 3.0) -> int:
        try:
            while True:
                await asyncio.wait_for(self.connection.recv(), timeout)
        except Exception:
            pass
        return self.connection.close_code  # type: ignore[return-value]


async def open_client(
    live: Live, token: str | None, *, version: int = PROTOCOL_VERSION
) -> WsClient:
    client = WsClient(await connect(live.ws_url))
    if token is not None:
        await client.send(
            "hello", {"protocol_version": version, "access_token": token}, with_id=False
        )
    return client
