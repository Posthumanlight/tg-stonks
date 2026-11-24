import httpx
import pytest
from fastapi import FastAPI

from app.combat.ground.resolver import IllegalAction
from app.shared.clock import FakeClock
from app.shared.dispatch import Dispatcher, UnknownMessage
from app.shared.errors import GameError, install_error_handlers
from app.shared.ratelimit import KeyedRateLimiter, TokenBucket


def test_token_bucket_refills_over_time() -> None:
    clock = FakeClock()
    bucket = TokenBucket(rate_per_s=2, burst=3, clock=clock)
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]
    assert bucket.retry_after() == pytest.approx(0.5)
    clock.advance(0.5)
    assert bucket.take() and not bucket.take()
    clock.advance(100)
    assert [bucket.take() for _ in range(4)] == [
        True,
        True,
        True,
        False,
    ]  # capped at burst


def test_keyed_limiter_is_per_key_and_evicts() -> None:
    clock = FakeClock()
    limiter = KeyedRateLimiter.per_minute(2, clock)
    assert limiter.hit("a") is None and limiter.hit("a") is None
    assert limiter.hit("a") == pytest.approx(30)
    assert limiter.hit("b") is None
    small = KeyedRateLimiter(1, 1, clock, max_keys=2)
    for key in ("x", "y", "z"):
        assert small.hit(key) is None
    assert small.hit("x") is None  # "x" was evicted, so it starts with a fresh bucket


async def test_dispatcher_routes_by_type() -> None:
    dispatcher: Dispatcher[str] = Dispatcher()

    @dispatcher.on("greet")
    async def greet(ctx: str, payload: dict) -> str:
        return f"{ctx}:{payload['name']}"

    assert await dispatcher.dispatch("greet", "ctx", {"name": "x"}) == "ctx:x"
    assert dispatcher.handles("greet") and not dispatcher.handles("other")
    with pytest.raises(UnknownMessage):
        await dispatcher.dispatch("other", "ctx", {})
    with pytest.raises(ValueError):
        dispatcher.add("greet", greet)


async def test_error_handlers_render_reason_keys() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/game")
    async def game() -> None:
        raise GameError("auth.rate_limited", 429, headers={"Retry-After": "3"})

    @app.get("/illegal")
    async def illegal() -> None:
        raise IllegalAction("move.forbidden.too_far")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/game")
        assert response.status_code == 429
        assert response.json() == {"reason_key": "auth.rate_limited"}
        assert response.headers["retry-after"] == "3"
        response = await client.get("/illegal")
        assert response.status_code == 400
        assert response.json() == {"reason_key": "move.forbidden.too_far"}
