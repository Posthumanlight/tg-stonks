from app.api.world import build_galaxy_view
from app.content.worldgen import load_worldgen_content
from app.protocol import PROTOCOL_VERSION
from app.world.generator import WorldGenerator

from tests.support import WORLD_SEED, TestApp

SEED = WORLD_SEED


async def test_health_is_public(test_app: TestApp) -> None:
    response = await test_app.client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "protocol_version": PROTOCOL_VERSION}


async def test_galaxy_requires_auth(test_app: TestApp) -> None:
    response = await test_app.client.get("/api/world/galaxy")
    assert response.status_code == 401
    assert response.json()["reason_key"] == "auth.missing_token"


async def test_galaxy_payload_and_etag(test_app: TestApp) -> None:
    headers = await test_app.auth_headers()
    client = test_app.client
    content = load_worldgen_content()
    response = await client.get("/api/world/galaxy", headers=headers)
    assert response.status_code == 200
    etag = response.headers["etag"]
    body = response.json()

    assert len(body["stars"]) == content.galaxy.star_count
    assert [s["index"] for s in body["stars"]] == list(range(len(body["stars"])))
    star_count = len(body["stars"])
    assert all(0 <= l["a"] < l["b"] < star_count for l in body["links"])
    assert {s["star_class"] for s in body["stars"]} <= set(content.stars.classes)

    again = await client.get("/api/world/galaxy", headers=headers)
    assert again.headers["etag"] == etag

    cached = await client.get(
        "/api/world/galaxy", headers={**headers, "If-None-Match": etag}
    )
    assert cached.status_code == 304
    assert cached.content == b""

    stale = await client.get(
        "/api/world/galaxy", headers={**headers, "If-None-Match": '"x"'}
    )
    assert stale.status_code == 200


def test_galaxy_view_is_deterministic() -> None:
    content = load_worldgen_content()
    first = build_galaxy_view(WorldGenerator(SEED, content), {})
    second = build_galaxy_view(WorldGenerator(SEED, content), {})
    assert first == second
    assert first != build_galaxy_view(WorldGenerator(SEED + 1, content), {})
