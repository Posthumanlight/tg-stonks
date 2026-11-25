from tests.support import TestApp


async def test_demo_is_created_once_per_user(test_app: TestApp) -> None:
    headers = await test_app.auth_headers()
    first = await test_app.client.post("/api/combats/demo", headers=headers)
    assert first.status_code == 200
    combat_id = first.json()["combat_id"]
    again = await test_app.client.post("/api/combats/demo", headers=headers)
    assert again.json()["combat_id"] == combat_id  # one active hotseat per user

    listed = await test_app.client.get("/api/combats", headers=headers)
    assert [(c["combat_id"], c["mode"], c["status"]) for c in listed.json()] == [
        (combat_id, "hotseat", "active")
    ]


async def test_combats_are_per_user_and_need_auth(test_app: TestApp) -> None:
    assert (await test_app.client.post("/api/combats/demo")).status_code == 401
    alice = await test_app.auth_headers("alice")
    bob = await test_app.auth_headers("bob")
    a = (await test_app.client.post("/api/combats/demo", headers=alice)).json()[
        "combat_id"
    ]
    b = (await test_app.client.post("/api/combats/demo", headers=bob)).json()[
        "combat_id"
    ]
    assert a != b
    listed = await test_app.client.get("/api/combats", headers=bob)
    assert [c["combat_id"] for c in listed.json()] == [b]


async def test_demo_combats_spread_over_workers(test_app: TestApp) -> None:
    router = test_app.app.state.combat_router
    for name in ("player1", "player2"):
        headers = await test_app.auth_headers(name)
        await test_app.client.post("/api/combats/demo", headers=headers)
    assert sorted(router._backend.loads()) == [1, 1]  # least-loaded placement


# --- custom battles ----------------------------------------------------------------


async def _defaults(test_app: TestApp, headers: dict[str, str]) -> dict:
    builder = await test_app.client.get("/api/combats/builder", headers=headers)
    return builder.json()["defaults"]


async def test_builder_view_and_etag(test_app: TestApp) -> None:
    assert (await test_app.client.get("/api/combats/builder")).status_code == 401
    headers = await test_app.auth_headers()
    response = await test_app.client.get("/api/combats/builder", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert [f["id"] for f in body["factions"]] == ["concord", "brood"]
    concord = {u["unit_type"]: u for u in body["factions"][0]["units"]}
    assert concord["line_troopers"]["models"] == {"min": 5, "max": 10, "default": 10}
    assert body["terrain"]["wall"] == {"passable": False}
    assert body["zones"] is None and body["board"]["factions"] is None
    assert [s["faction"] for s in body["defaults"]["sides"]] == ["concord", "brood"]
    assert body["limits"]["max_units_per_side"] >= 1
    cached = await test_app.client.get(
        "/api/combats/builder",
        headers={**headers, "If-None-Match": response.headers["etag"]},
    )
    assert cached.status_code == 304


async def test_custom_battle_uses_the_request(test_app: TestApp) -> None:
    headers = await test_app.auth_headers()
    request = await _defaults(test_app, headers)
    request["sides"][0]["units"] = request["sides"][0]["units"][:1]
    request["sides"][0]["units"][0]["models"] = 5
    response = await test_app.client.post(
        "/api/combats/custom", json=request, headers=headers
    )
    assert response.status_code == 201
    stored = await test_app.app.state.combat_store.load(response.json()["combat_id"])
    assert stored.setup["factions"] == ["concord", "brood"]
    assert stored.setup["units"][0] == {
        "unit_type": "line_troopers",
        "side": 0,
        "origin": [2, 1],
        "models": 5,
    }
    assert [u["side"] for u in stored.setup["units"]] == [0, 1, 1, 1]


async def test_custom_battle_errors_are_located(test_app: TestApp) -> None:
    headers = await test_app.auth_headers()
    request = await _defaults(test_app, headers)
    request["sides"][1]["units"][2]["unit_type"] = "warden"  # a Concord unit
    response = await test_app.client.post(
        "/api/combats/custom", json=request, headers=headers
    )
    assert response.status_code == 400
    assert response.json() == {
        "reason_key": "setup.wrong_faction",
        "detail": {"side": 1, "unit": 2},
    }
    request["sides"].append(request["sides"][0])  # three sides: not a valid request
    response = await test_app.client.post(
        "/api/combats/custom", json=request, headers=headers
    )
    assert response.json()["reason_key"] == "request.invalid"
    assert await test_app.app.state.combat_store.list_for_owner(1) == []


async def test_one_active_battle_then_abandon(test_app: TestApp) -> None:
    alice = await test_app.auth_headers("alice")
    bob = await test_app.auth_headers("bob")
    request = await _defaults(test_app, alice)
    first = await test_app.client.post(
        "/api/combats/custom", json=request, headers=alice
    )
    combat_id = first.json()["combat_id"]
    again = await test_app.client.post(
        "/api/combats/custom", json=request, headers=alice
    )
    assert (again.status_code, again.json()["reason_key"]) == (
        409,
        "combat.already_active",
    )
    # The quick battle resumes the active fight instead.
    quick = await test_app.client.post("/api/combats/demo", headers=alice)
    assert quick.json()["combat_id"] == combat_id

    url = f"/api/combats/{combat_id}/abandon"
    assert (await test_app.client.post(url, headers=bob)).status_code == 403
    assert (await test_app.client.post(url, headers=alice)).status_code == 204
    finished = await test_app.client.post(url, headers=alice)
    assert (finished.status_code, finished.json()["reason_key"]) == (
        409,
        "combat.finished",
    )
    missing = await test_app.client.post("/api/combats/nope/abandon", headers=alice)
    assert missing.status_code == 404
    listed = await test_app.client.get("/api/combats", headers=alice)
    assert [c["status"] for c in listed.json()] == ["abandoned"]

    fresh = await test_app.client.post(
        "/api/combats/custom", json=request, headers=alice
    )
    assert fresh.status_code == 201 and fresh.json()["combat_id"] != combat_id
