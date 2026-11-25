"""Lobby rooms over the WebSocket: per-viewer pushes, presence, the battle start, and
each player acting only for their side once it begins."""

from .conftest import Live, WsClient, open_client

ROOM = {"name": "Duel", "private": True, "points_limit": 0, "timer_s": 0}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _client(live: Live, token: str) -> WsClient:
    client = await open_client(live, token)
    await client.recv()  # welcome
    return client


async def test_room_flow_to_an_online_battle(live: Live) -> None:
    alice, bob = await live.token("alice"), await live.token("bob")
    room = (await live.http.post("/api/rooms", json=ROOM, headers=_auth(alice))).json()
    rid = room["room_id"]

    host = await _client(live, alice)
    await host.send("room.subscribe", {"room_id": rid})
    state, _ = await host.recv_until("room.state")
    assert state["payload"]["your_side"] == 0 and len(state["payload"]["players"]) == 1

    stranger = await _client(live, await live.token("carol"))
    await stranger.send("room.subscribe", {"room_id": rid})
    error, _ = await stranger.recv_until("error")
    assert error["payload"]["reason_key"] == "room.not_member"

    await live.http.post(
        "/api/rooms/join", json={"code": room["code"]}, headers=_auth(bob)
    )
    state, _ = await host.recv_until("room.state")
    assert [p["name"] for p in state["payload"]["players"]] == ["alice", "bob"]

    guest = await _client(live, bob)
    await guest.send("room.subscribe", {"room_id": rid})
    state, _ = await guest.recv_until("room.state")
    assert state["payload"]["your_side"] == 1

    sides = (await live.http.get("/api/combats/builder", headers=_auth(alice))).json()[
        "defaults"
    ]["sides"]
    await live.http.post(f"/api/rooms/{rid}/ready", json=sides[0], headers=_auth(alice))
    seen, _ = await guest.recv_until("room.state")
    host_card = seen["payload"]["players"][0]
    assert host_card["ready"] and host_card["faction"] == "concord"
    assert host_card["points"] == 440 and host_card["unit_count"] == 4
    assert seen["payload"]["your_army"] is None  # never the opponent's positions

    await live.http.post(f"/api/rooms/{rid}/ready", json=sides[1], headers=_auth(bob))
    started, _ = await host.recv_until("room.started")
    combat_id = started["payload"]["combat_id"]
    assert (await guest.recv_until("room.started"))[0]["payload"][
        "combat_id"
    ] == combat_id

    # The battle: both are seated, each acts only for their own side.
    for client in (host, guest):
        await client.send("combat.subscribe", {"combat_id": combat_id})
    snapshot, _ = await host.recv_until("combat.snapshot")
    await guest.recv_until("combat.snapshot")
    view = snapshot["payload"]["view"]
    active_side = next(
        u["side"] for u in view["units"] if u["uid"] == view["active"]["uid"]
    )
    idle, mover = (guest, host) if active_side == 0 else (host, guest)
    await idle.send(
        "combat.action", {"combat_id": combat_id, "intent": {"type": "skip"}}
    )
    error, _ = await idle.recv_until("error")
    assert error["payload"]["reason_key"] == "combat.not_your_turn"
    await mover.send(
        "combat.action", {"combat_id": combat_id, "intent": {"type": "skip"}}
    )
    await idle.recv_until("combat.events")  # the opponent sees the move


async def test_presence_and_the_guest_grace_period(live: Live) -> None:
    alice, bob = await live.token("alice"), await live.token("bob")
    room = (await live.http.post("/api/rooms", json=ROOM, headers=_auth(alice))).json()
    rid = room["room_id"]
    await live.http.post(
        "/api/rooms/join", json={"code": room["code"]}, headers=_auth(bob)
    )
    host = await _client(live, alice)
    await host.send("room.subscribe", {"room_id": rid})
    await host.recv_until("room.state")

    guest = await _client(live, bob)
    await guest.send("room.subscribe", {"room_id": rid})
    await host.recv_until("room.state")
    await guest.connection.close()  # the guest's tab goes away
    state, _ = await host.recv_until("room.state")
    assert [p["connected"] for p in state["payload"]["players"]] == [True, False]

    live.clock.advance(31, monotonic=True)
    await live.app.state.rooms.sweep()
    state, _ = await host.recv_until("room.state")
    assert (
        len(state["payload"]["players"]) == 1 and state["payload"]["status"] == "open"
    )
