"""Auth flows over HTTP (docs/architecture.md "Authentication")."""

import pytest

from tests.support import TestApp

COOKIE = "__Host-refresh"


def _set_cookie(response) -> str:
    return response.headers.get("set-cookie", "")


async def test_register_login_me_refresh_logout(test_app: TestApp) -> None:
    client = test_app.client
    user = await test_app.register("Alice_1")
    assert user["username"] == "Alice_1" and user["role"] == "player"

    login = await client.post(
        "/api/auth/login", json={"username": "alice_1", "password": "correct horse"}
    )  # usernames are case-insensitive
    assert login.status_code == 200
    body = login.json()
    assert body["expires_in"] == 900 and body["user"]["username"] == "Alice_1"
    cookie = _set_cookie(login)
    for flag in (f"{COOKIE}=", "HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert flag.lower() in cookie.lower()

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["user_id"] == user["user_id"]

    old_refresh = client.cookies.get(COOKIE)
    refreshed = await client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get(COOKIE) != old_refresh  # rotated

    out = await client.post("/api/auth/logout")
    assert out.status_code == 204
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_registration_rules(test_app: TestApp) -> None:
    client = test_app.client
    await test_app.register("bob_bob")
    for username, password, reason in [
        ("BOB_bob", "long enough pw", "auth.username_taken"),
        ("ab", "long enough pw", "auth.username_invalid"),
        ("has space", "long enough pw", "auth.username_invalid"),
        ("carol", "short", "auth.password_invalid"),
    ]:
        response = await client.post(
            "/api/auth/register", json={"username": username, "password": password}
        )
        assert response.json()["reason_key"] == reason, username
    response = await client.post("/api/auth/register", json={"username": "x"})
    assert response.status_code == 400
    assert response.json()["reason_key"] == "request.invalid"


async def test_bad_credentials_are_generic(test_app: TestApp) -> None:
    await test_app.register()
    for username, password in [("alice", "wrong password"), ("nobody", "whatever pw")]:
        response = await test_app.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 401
        assert response.json() == {"reason_key": "auth.invalid_credentials"}


async def _refresh_with(test_app: TestApp, raw: str):
    test_app.client.cookies.clear()
    test_app.client.cookies.set(COOKIE, raw)
    return await test_app.client.post("/api/auth/refresh")


async def test_refresh_token_reuse_revokes_the_session(test_app: TestApp) -> None:
    client = test_app.client
    await test_app.register()
    await test_app.login()
    stolen = client.cookies.get(COOKIE)
    assert (await client.post("/api/auth/refresh")).status_code == 200
    legit = client.cookies.get(COOKIE)

    # within the race window a replay is treated as a concurrent tab
    replay = await _refresh_with(test_app, stolen)
    assert (
        replay.status_code == 409 and replay.json()["reason_key"] == "auth.refresh_race"
    )

    # later, presenting the rotated token again is theft: the whole family dies,
    # including the legitimate successor token
    test_app.clock.advance(60)
    assert (await _refresh_with(test_app, stolen)).status_code == 401
    assert (await _refresh_with(test_app, legit)).status_code == 401


async def test_refresh_requires_same_origin(test_app: TestApp) -> None:
    await test_app.register()
    await test_app.login()
    evil = await test_app.client.post(
        "/api/auth/refresh", headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403 and evil.json()["reason_key"] == "auth.bad_origin"


async def test_access_token_expires(test_app: TestApp) -> None:
    headers = await test_app.auth_headers()
    assert (
        await test_app.client.get("/api/auth/me", headers=headers)
    ).status_code == 200
    test_app.clock.advance(900 + 31)  # TTL + leeway
    response = await test_app.client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["reason_key"] == "auth.invalid_token"


async def test_logout_all_revokes_every_session(test_app: TestApp) -> None:
    client = test_app.client
    await test_app.register()
    first = (await test_app.login())["access_token"]
    first_cookie = client.cookies.get(COOKIE)
    await test_app.login()  # a second device
    response = await client.post(
        "/api/auth/logout-all", headers={"Authorization": f"Bearer {first}"}
    )
    assert response.status_code == 204
    assert (await _refresh_with(test_app, first_cookie)).status_code == 401


async def test_login_rate_limit(test_app: TestApp) -> None:
    await test_app.register()
    statuses = []
    for _ in range(7):
        response = await test_app.client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong password"}
        )
        statuses.append(response.status_code)
    assert statuses[:5] == [401] * 5 and statuses[5] == 429
    assert int(response.headers["retry-after"]) > 0
    test_app.clock.advance(60)
    assert (await test_app.login())["user"]["username"] == "alice"


@pytest.mark.parametrize("token", ["", "garbage", "a.b.c"])
async def test_garbage_tokens_are_rejected(test_app: TestApp, token: str) -> None:
    response = await test_app.client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


async def test_plain_http_dev_uses_a_bare_cookie(app_factory) -> None:
    async with app_factory(auth_cookie_secure=False) as t:
        await t.register()
        login = await t.client.post(
            "/api/auth/login", json={"username": "alice", "password": "correct horse"}
        )
        cookie = _set_cookie(login)
        assert cookie.startswith("refresh=") and "secure" not in cookie.lower()
