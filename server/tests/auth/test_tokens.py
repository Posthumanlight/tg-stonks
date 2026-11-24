import pytest
from joserfc import jwt
from joserfc.jwk import OctKey

from app.auth.passwords import Argon2Hasher
from app.auth.tokens import AUDIENCE, ISSUER, TokenService
from app.shared.clock import FakeClock
from app.shared.errors import GameError

SECRET = b"s" * 40
OTHER = b"o" * 40


def _service(clock: FakeClock, **kw) -> TokenService:
    return TokenService(kw.pop("secret", SECRET), ttl_s=900, clock=clock, **kw)


def test_issue_and_verify_round_trip() -> None:
    clock = FakeClock()
    service = _service(clock)
    token = service.issue(7, "admin", "family-1")
    principal = service.verify(token.token)
    assert (principal.user_id, principal.role, principal.session_id) == (
        7,
        "admin",
        "family-1",
    )
    assert principal.expires_at == int(clock.now()) + 900


def test_expiry_with_leeway() -> None:
    clock = FakeClock()
    service = _service(clock)
    token = service.issue(1, "player", "f").token
    clock.advance(900 + 29)
    service.verify(token)  # inside the 30 s leeway
    clock.advance(2)
    with pytest.raises(GameError, match="auth.invalid_token"):
        service.verify(token)


def test_wrong_key_and_rotation() -> None:
    clock = FakeClock()
    old = _service(clock, secret=OTHER).issue(1, "player", "f").token
    with pytest.raises(GameError):
        _service(clock).verify(old)
    rotated = _service(clock, previous_secret=OTHER)
    assert rotated.verify(old).user_id == 1  # the previous key still verifies


def test_algorithm_is_pinned() -> None:
    clock = FakeClock()
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "1",
        "exp": int(clock.now()) + 60,
        "sid": "f",
    }
    key = OctKey.import_key(SECRET)
    for alg in ("HS512", "HS384"):
        forged = jwt.encode({"alg": alg}, claims, key, algorithms=[alg])
        with pytest.raises(GameError):
            _service(clock).verify(forged)


def test_claims_are_required() -> None:
    clock = FakeClock()
    service = _service(clock)
    good = service.issue(1, "player", "f").token
    header = {"alg": "HS256", "kid": jwt.decode(good, service._verifying).header["kid"]}
    key = service._signing
    for missing in ("iss", "aud", "sub", "exp", "sid"):
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "1",
            "exp": int(clock.now()) + 60,
            "sid": "f",
        }
        del claims[missing]
        with pytest.raises(GameError):
            service.verify(jwt.encode(header, claims, key))


async def test_argon2_hasher() -> None:
    hasher = Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1)
    hashed = await hasher.hash("correct horse")
    assert hashed.startswith("$argon2id$")
    assert await hasher.verify(hashed, "correct horse")
    assert not await hasher.verify(hashed, "wrong")
    assert not await hasher.verify("not-a-hash", "x")
    stronger = Argon2Hasher(time_cost=2, memory_cost=1024, parallelism=1)
    assert stronger.needs_rehash(hashed) and not hasher.needs_rehash(hashed)
    await hasher.verify_dummy("anything")
