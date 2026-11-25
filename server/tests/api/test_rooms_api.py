"""Lobby rooms over HTTP (docs/lobby-rooms.md): create, search, join by code, ready,
the battle start, kick/leave and expiry. Pushes are covered in tests/ws."""

from tests.support import TestApp

ROOM = {"name": "Friday fight", "private": False, "points_limit": 1000, "timer_s": 45}


async def _defaults(test_app: TestApp, headers: dict[str, str]) -> list[dict]:
    builder = await test_app.client.get("/api/combats/builder", headers=headers)
    return builder.json()["defaults"]["sides"]


async def _create(test_app: TestApp, headers: dict[str, str], **changes) -> dict:
    response = await test_app.client.post(
        "/api/rooms", json={**ROOM, **changes}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_builder_offers_room_presets_and_zones(test_app: TestApp) -> None:
    headers = await test_app.auth_headers()
    body = (await test_app.client.get("/api/combats/builder", headers=headers)).json()
    rooms = body["rooms"]
    assert rooms["points_presets"] == [500, 1000, 1500, 0]
    assert rooms["timer_presets"][0] == 45 and 0 in rooms["timer_presets"]
    assert [z["side"] for z in rooms["zones"]] == [0, 1]
    assert body["zones"] is None  # hotseat deploys anywhere


async def test_create_search_and_join_by_code(test_app: TestApp) -> None:
    alice = await test_app.auth_headers("alice")
    bad = await test_app.client.post(
        "/api/rooms", json={**ROOM, "points_limit": 777}, headers=alice
    )
    assert bad.json()["reason_key"] == "room.bad_points"
    room = await _create(test_app, alice)
    assert len(room["code"]) == 6
    again = await test_app.client.post("/api/rooms", json=ROOM, headers=alice)
    assert (again.status_code, again.json()["reason_key"]) == (
        409,
        "room.already_in_room",
    )
    mine = await test_app.client.get("/api/rooms/mine", headers=alice)
    assert mine.json() == {"room": room}

    carol = await test_app.auth_headers("carol")
    secret = await _create(test_app, carol, name="Secret", private=True)

    bob = await test_app.auth_headers("bob")
    found = await test_app.client.get(
        "/api/rooms", params={"q": "friday", "points": 1000}, headers=bob
    )
    assert [(r["room_id"], r["host_name"]) for r in found.json()["rooms"]] == [
        (room["room_id"], "alice")
    ]
    listed = await test_app.client.get("/api/rooms", headers=bob)
    assert secret["room_id"] not in [r["room_id"] for r in listed.json()["rooms"]]
    hidden = await test_app.client.post(
        f"/api/rooms/{secret['room_id']}/join", headers=bob
    )
    assert hidden.status_code == 404  # private: by code only
    joined = await test_app.client.post(
        "/api/rooms/join", json={"code": secret["code"].lower()}, headers=bob
    )
    assert joined.json() == secret
    full = await test_app.client.get("/api/rooms", params={"q": "secret"}, headers=bob)
    assert full.json()["rooms"] == []


async def test_both_ready_starts_an_online_battle(test_app: TestApp) -> None:
    alice, bob = await test_app.auth_headers("alice"), await test_app.auth_headers(
        "bob"
    )
    room = await _create(test_app, alice)
    rid = room["room_id"]
    await test_app.client.post(f"/api/rooms/{rid}/join", headers=bob)
    concord, brood = await _defaults(test_app, alice)

    wrong_zone = await test_app.client.post(
        f"/api/rooms/{rid}/ready", json=concord, headers=bob  # side 0's spots
    )
    assert wrong_zone.status_code == 400
    assert wrong_zone.json() == {
        "reason_key": "setup.outside_zone",
        "detail": {"side": 1, "unit": 0},
    }
    first = await test_app.client.post(
        f"/api/rooms/{rid}/ready", json=concord, headers=alice
    )
    assert first.json() == {"combat_id": None}
    started = await test_app.client.post(
        f"/api/rooms/{rid}/ready", json=brood, headers=bob
    )
    combat_id = started.json()["combat_id"]
    assert combat_id is not None

    for headers in (alice, bob):
        listed = await test_app.client.get("/api/combats", headers=headers)
        assert [(c["combat_id"], c["mode"]) for c in listed.json()] == [
            (combat_id, "pvp")
        ]
        assert (
            await test_app.client.get("/api/rooms/mine", headers=headers)
        ).json() == {"room": None}
    busy = await test_app.client.post("/api/rooms", json=ROOM, headers=alice)
    assert busy.json()["reason_key"] == "combat.already_active"

    # Leaving an online battle is a surrender: it ends, and the opponent wins.
    gave_up = await test_app.client.post(
        f"/api/combats/{combat_id}/abandon", headers=bob
    )
    assert gave_up.status_code == 204
    listed = await test_app.client.get("/api/combats", headers=alice)
    assert listed.json()[0]["status"] == "finished"
    await _create(test_app, alice)  # free again


async def test_points_limit_and_unready(test_app: TestApp) -> None:
    alice = await test_app.auth_headers("alice")
    room = await _create(test_app, alice, points_limit=500)
    rid = room["room_id"]
    concord, _ = await _defaults(test_app, alice)
    bigger = {**concord, "units": concord["units"] + [concord["units"][2]]}
    bigger["units"][-1] = {**bigger["units"][-1], "origin": [12, 2]}
    over = await test_app.client.post(
        f"/api/rooms/{rid}/ready", json=bigger, headers=alice
    )
    assert over.json()["reason_key"] == "setup.over_points"
    assert (
        await test_app.client.post(
            f"/api/rooms/{rid}/ready", json=concord, headers=alice
        )
    ).status_code == 200
    assert (
        await test_app.client.post(f"/api/rooms/{rid}/unready", headers=alice)
    ).status_code == 204


async def test_kick_leave_and_close(test_app: TestApp) -> None:
    alice, bob, carol = (
        await test_app.auth_headers("alice"),
        await test_app.auth_headers("bob"),
        await test_app.auth_headers("carol"),
    )
    room = await _create(test_app, alice)
    rid = room["room_id"]
    await test_app.client.post(f"/api/rooms/{rid}/join", headers=bob)
    not_host = await test_app.client.post(f"/api/rooms/{rid}/kick", headers=bob)
    assert not_host.json()["reason_key"] == "room.not_host"
    assert (
        await test_app.client.post(f"/api/rooms/{rid}/kick", headers=alice)
    ).status_code == 204
    back = await test_app.client.post(f"/api/rooms/{rid}/join", headers=bob)
    assert back.json()["reason_key"] == "room.kicked"
    assert (await test_app.client.get("/api/rooms/mine", headers=bob)).json() == {
        "room": None
    }

    await test_app.client.post(f"/api/rooms/{rid}/join", headers=carol)
    await test_app.client.post(f"/api/rooms/{rid}/leave", headers=carol)
    listed = await test_app.client.get("/api/rooms", headers=carol)
    assert [r["room_id"] for r in listed.json()["rooms"]] == [rid]  # open again
    await test_app.client.post(f"/api/rooms/{rid}/leave", headers=alice)
    gone = await test_app.client.post(
        "/api/rooms/join", json={"code": room["code"]}, headers=carol
    )
    assert gone.status_code == 404


async def test_idle_rooms_expire(test_app: TestApp) -> None:
    alice = await test_app.auth_headers("alice")
    await _create(test_app, alice)
    test_app.clock.advance(1801)
    await test_app.app.state.rooms.sweep()
    token = (await test_app.login("alice"))["access_token"]  # the old one expired
    mine = await test_app.client.get(
        "/api/rooms/mine", headers={"Authorization": f"Bearer {token}"}
    )
    assert mine.json() == {"room": None}


async def test_joining_by_code_is_rate_limited(test_app: TestApp) -> None:
    bob = await test_app.auth_headers("bob")
    for _ in range(20):
        miss = await test_app.client.post(
            "/api/rooms/join", json={"code": "ZZZZZZ"}, headers=bob
        )
        assert miss.status_code == 404
    limited = await test_app.client.post(
        "/api/rooms/join", json={"code": "ZZZZZZ"}, headers=bob
    )
    assert limited.status_code == 429 and "retry-after" in limited.headers
