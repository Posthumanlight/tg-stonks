"""Access tokens: short-lived JWTs (HS256) issued and verified with joserfc."""

import hashlib
import secrets
from dataclasses import dataclass

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, OctKey

from app.shared.clock import Clock
from app.shared.errors import GameError

ISSUER = "tg-stonks"
AUDIENCE = "tg-stonks-client"
ALGORITHM = "HS256"
LEEWAY_S = 30


@dataclass(frozen=True, slots=True)
class AccessToken:
    token: str
    expires_in: int  # seconds


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is calling, straight from verified claims (no DB lookup)."""

    user_id: int
    role: str
    session_id: str  # refresh-token family
    expires_at: int  # unix seconds


def _key(secret: bytes) -> OctKey:
    # The key id is derived from the key, so rotation needs no extra config.
    kid = hashlib.sha256(secret).hexdigest()[:16]
    return OctKey.import_key(secret, {"kid": kid})


class TokenService:
    def __init__(
        self,
        secret: bytes,
        *,
        ttl_s: int,
        clock: Clock,
        previous_secret: bytes | None = None,
    ) -> None:
        self._signing = _key(secret)
        keys = [self._signing] + ([_key(previous_secret)] if previous_secret else [])
        self._verifying = KeySet(keys)
        self._ttl = ttl_s
        self._clock = clock

    def issue(self, user_id: int, role: str, session_id: str) -> AccessToken:
        now = int(self._clock.now())
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": str(user_id),
            "iat": now,
            "exp": now + self._ttl,
            "jti": secrets.token_urlsafe(12),
            "role": role,
            "sid": session_id,
        }
        header = {"alg": ALGORITHM, "kid": self._signing.kid}
        return AccessToken(jwt.encode(header, claims, self._signing), self._ttl)

    def verify(self, token: str) -> Principal:
        """Raises GameError(auth.invalid_token, 401) on any problem."""
        try:
            decoded = jwt.decode(token, self._verifying, algorithms=[ALGORITHM])
            registry = jwt.JWTClaimsRegistry(
                now=lambda: int(self._clock.now()),
                leeway=LEEWAY_S,
                iss={"essential": True, "value": ISSUER},
                aud={"essential": True, "value": AUDIENCE},
                sub={"essential": True},
                exp={"essential": True},
                sid={"essential": True},
            )
            registry.validate(decoded.claims)
            claims = decoded.claims
            return Principal(
                user_id=int(claims["sub"]),
                role=str(claims.get("role", "player")),
                session_id=str(claims["sid"]),
                expires_at=int(claims["exp"]),
            )
        except (JoseError, ValueError, KeyError, TypeError) as exc:
            raise GameError("auth.invalid_token", 401) from exc
