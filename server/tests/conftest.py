"""Shared fixtures: an app wired with SQLite, a fake clock and a cheap password hasher."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.main import create_app
from app.persistence.db import Base, create_engine
from app.shared.clock import FakeClock

from tests.support import ORIGIN, TestApp, cheap_hasher, test_settings


@pytest.fixture
def app_factory(tmp_path: Path) -> Callable[..., object]:
    """`async with app_factory(**settings) as t:` gives a running app (`TestApp`)."""

    @asynccontextmanager
    async def make(**settings_overrides: object) -> AsyncIterator[TestApp]:
        engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        clock = FakeClock()
        app = create_app(
            settings=test_settings(**settings_overrides),
            sessionmaker=async_sessionmaker(engine, expire_on_commit=False),
            client_dist=None,
            clock=clock,
            password_hasher=cheap_hasher(),
        )
        try:
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url=ORIGIN, headers={"Origin": ORIGIN}
                ) as client:
                    yield TestApp(app, client, clock)
        finally:
            await engine.dispose()

    return make


@pytest.fixture
async def test_app(app_factory) -> AsyncIterator[TestApp]:
    async with app_factory() as t:
        yield t
