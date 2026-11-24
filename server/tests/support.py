"""Test helpers shared across test packages (fixtures live in conftest.py)."""

from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from app.auth.passwords import Argon2Hasher
from app.config import Settings
from app.shared.clock import FakeClock

TEST_SECRET = "test-secret-" + "x" * 40
WORLD_SEED = 42
ORIGIN = "https://test"


def test_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "sqlite://",
        "world_seed": WORLD_SEED,
        "auth_secret": TEST_SECRET,
        "auth_cookie_secure": True,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


test_settings.__test__ = False  # not a pytest test despite the name


def cheap_hasher() -> Argon2Hasher:
    return Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1)


@dataclass
class TestApp:
    __test__ = False

    app: FastAPI
    client: httpx.AsyncClient
    clock: FakeClock

    async def register(
        self, username: str = "alice", password: str = "correct horse"
    ) -> dict:
        response = await self.client.post(
            "/api/auth/register", json={"username": username, "password": password}
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def login(
        self, username: str = "alice", password: str = "correct horse"
    ) -> dict:
        response = await self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def auth_headers(self, username: str = "alice") -> dict[str, str]:
        await self.register(username)
        token = (await self.login(username))["access_token"]
        return {"Authorization": f"Bearer {token}"}
