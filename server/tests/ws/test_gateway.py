"""The /ws gateway end to end: a real uvicorn server and a real WebSocket client."""

import asyncio
import json

from app.ws.connection import CloseCode, Connection

from .conftest import open_client


async def test_handshake_welcomes_the_user(live) -> None:
    client = await open_client(live, await live.token())
    welcome = await client.recv()
    assert welcome["type"] == "welcome"
    assert welcome["payload"]["protocol_version"] == 2


async def test_handshake_failures_close_with_codes(live) -> None:
    token = await live.token()
    silent = await open_client(live, None)
    assert await silent.close_code() == CloseCode.HANDSHAKE_TIMEOUT
    bad_token = await open_client(live, "nope")
    assert await bad_token.close_code() == CloseCode.UNAUTHORIZED
    old = await open_client(live, token, version=1)
    error = await old.recv()
    assert error["payload"]["reason_key"] == "protocol.version_mismatch"
    assert await old.close_code() == CloseCode.PROTOCOL_MISMATCH


async def test_garbage_closes_with_4400(live) -> None:
    client = await open_client(live, await live.token())
    await client.recv()
    await client.connection.send("{not json")
    assert await client.close_code() == CloseCode.BAD_MESSAGE


async def test_subscribe_act_and_fan_out(live) -> None:
    token = await live.token()
    combat_id = await live.demo(token)
    tab1, tab2 = await open_client(live, token), await open_client(live, token)
    for tab in (tab1, tab2):
        await tab.recv()  # welcome
        request = await tab.send("combat.subscribe", {"combat_id": combat_id})
        snapshot, _ = await tab.recv_until("combat.snapshot")
        assert snapshot["payload"]["board"]["width"] == 24
        ack, _ = await tab.recv_until("ack")
        assert ack["id"] == request

    request = await tab1.send(
        "combat.action", {"combat_id": combat_id, "intent": {"type": "wait"}}
    )
    update, _ = await tab1.recv_until("combat.events")
    ack, _ = await tab1.recv_until("ack")
    assert ack["id"] == request  # the push arrives before the ack
    other, _ = await tab2.recv_until("combat.events")
    assert other["payload"]["view"] == update["payload"]["view"]

    # an illegal action: an error for the sender only, nothing pushed
    request = await tab1.send(
        "combat.action",
        {
            "combat_id": combat_id,
            "intent": {"type": "move", "to": [11, 11]},
        },  # deep water
    )
    error, _ = await tab1.recv_until("error")
    assert error["id"] == request and error["payload"]["reason_key"].startswith(
        "move.forbidden"
    )
    await tab2.send("ping")
    pong, skipped = await tab2.recv_until("pong")
    assert not [m for m in skipped if m["type"] == "combat.events"]


async def test_strangers_cannot_subscribe(live) -> None:
    combat_id = await live.demo(await live.token("alice"))
    bob = await open_client(live, await live.token("bob"))
    await bob.recv()
    await bob.send("combat.subscribe", {"combat_id": combat_id})
    error, _ = await bob.recv_until("error")
    assert error["payload"]["reason_key"] == "combat.not_a_participant"


async def test_resync_from_last_seq(live) -> None:
    token = await live.token()
    combat_id = await live.demo(token)
    client = await open_client(live, token)
    await client.recv()
    await client.send("combat.subscribe", {"combat_id": combat_id})
    snapshot, _ = await client.recv_until("combat.snapshot")
    seq = snapshot["payload"]["view"]["seq"]
    await client.send(
        "combat.action", {"combat_id": combat_id, "intent": {"type": "wait"}}
    )
    await client.recv_until("ack")
    await client.connection.close()

    again = await open_client(live, token)
    await again.recv()
    await again.send("combat.subscribe", {"combat_id": combat_id, "last_seq": seq})
    catch_up, _ = await again.recv_until("combat.events")
    assert catch_up["payload"]["from_seq"] == seq and catch_up["payload"]["events"]


async def test_token_expiry_and_refresh(live) -> None:
    token = await live.token()
    client = await open_client(live, token)
    await client.recv()
    live.clock.advance(800, monotonic=False)
    fresh = (
        await live.http.post(
            "/api/auth/login", json={"username": "alice", "password": "correct horse"}
        )
    ).json()["access_token"]
    await client.send("auth.refresh", {"access_token": fresh})
    await client.recv_until("ack")
    live.clock.advance(200, monotonic=False)  # the old token would have expired
    await client.send("ping")
    await client.recv_until("pong")
    live.clock.advance(900 + 60, monotonic=False)
    assert await client.close_code() == CloseCode.UNAUTHORIZED


async def test_rate_limit_and_idle(live) -> None:
    client = await open_client(live, await live.token())
    await client.recv()
    for _ in range(45):  # burst 40 (the fake clock doesn't refill the bucket)
        await client.send("ping", with_id=False)
    assert await client.close_code() == CloseCode.RATE_LIMITED

    quiet = await open_client(live, await live.token("bob"))
    await quiet.recv()
    live.clock.advance(61)
    assert await quiet.close_code() == CloseCode.GOING_AWAY


async def test_slow_clients_are_dropped_not_waited_for() -> None:
    class Stalled:
        async def send_text(self, text: str) -> None:
            await asyncio.sleep(3600)

    from app.auth.tokens import Principal
    from app.shared.clock import FakeClock

    connection = Connection(Stalled(), Principal(1, "player", "s", 0), FakeClock())  # type: ignore[arg-type]
    connection.start()
    for i in range(300):
        connection.send({"type": "x", "n": i})
    assert connection.close_code == CloseCode.SERVER_ERROR
    await connection.stop()
    json.dumps({})  # keep the import used
