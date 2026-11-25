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
