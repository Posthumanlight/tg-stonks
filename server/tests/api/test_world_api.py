from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.world import build_galaxy_view
from app.content.worldgen import load_worldgen_content
from app.main import create_app
from app.persistence.db import Base, create_engine
from app.protocol import PROTOCOL_VERSION
from app.world.generator import WorldGenerator

SEED = 42


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    app = create_app(
        sessionmaker=async_sessionmaker(engine, expire_on_commit=False),
        world_seed=SEED,
        client_dist=None,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    await engine.dispose()


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "protocol_version": PROTOCOL_VERSION}


async def test_galaxy_payload_and_etag(client: httpx.AsyncClient) -> None:
    content = load_worldgen_content()
    response = await client.get("/api/world/galaxy")
    assert response.status_code == 200
    etag = response.headers["etag"]
    body = response.json()

    assert len(body["stars"]) == content.galaxy.star_count
    assert [s["index"] for s in body["stars"]] == list(range(len(body["stars"])))
    star_count = len(body["stars"])
    assert all(0 <= l["a"] < l["b"] < star_count for l in body["links"])
    assert {s["star_class"] for s in body["stars"]} <= set(content.stars.classes)

    again = await client.get("/api/world/galaxy")
    assert again.headers["etag"] == etag

    cached = await client.get("/api/world/galaxy", headers={"If-None-Match": etag})
    assert cached.status_code == 304
    assert cached.content == b""

    stale = await client.get("/api/world/galaxy", headers={"If-None-Match": '"x"'})
    assert stale.status_code == 200


def test_galaxy_view_is_deterministic() -> None:
    content = load_worldgen_content()
    first = build_galaxy_view(WorldGenerator(SEED, content), {})
    second = build_galaxy_view(WorldGenerator(SEED, content), {})
    assert first == second
    assert first != build_galaxy_view(WorldGenerator(SEED + 1, content), {})
