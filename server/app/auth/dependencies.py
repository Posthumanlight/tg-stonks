"""FastAPI glue: the auth components on `app.state`, `current_user`, roles, limits."""

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.cookies import CookiePolicy
from app.auth.service import AuthService
from app.auth.tokens import Principal, TokenService
from app.shared.clock import Clock
from app.shared.errors import GameError
from app.shared.ratelimit import KeyedRateLimiter


@dataclass(frozen=True, slots=True)
class AuthLimits:
    login_ip: KeyedRateLimiter
    login_user: KeyedRateLimiter
    register_ip: KeyedRateLimiter
    refresh_ip: KeyedRateLimiter

    @classmethod
    def defaults(cls, clock: Clock) -> "AuthLimits":
        return cls(
            login_ip=KeyedRateLimiter.per_minute(10, clock),
            login_user=KeyedRateLimiter.per_minute(5, clock),
            register_ip=KeyedRateLimiter.per_hour(5, clock),
            refresh_ip=KeyedRateLimiter.per_minute(10, clock),
        )


@dataclass(frozen=True, slots=True)
class AuthComponents:
    service: AuthService
    tokens: TokenService
    limits: AuthLimits
    cookie: CookiePolicy


def get_auth(request: Request) -> AuthComponents:
    return request.app.state.auth


_bearer = HTTPBearer(auto_error=False)


async def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """The caller, from a verified access token. No DB lookup (role changes apply at the
    next refresh, ≤ 15 min)."""
    if credentials is None:
        raise GameError(
            "auth.missing_token", 401, headers={"WWW-Authenticate": "Bearer"}
        )
    return get_auth(request).tokens.verify(credentials.credentials)


def require_role(role: str) -> Callable[..., Awaitable[Principal]]:
    async def dependency(principal: Principal = Depends(current_user)) -> Principal:
        if principal.role != role:
            raise GameError("auth.forbidden", 403)
        return principal

    return dependency


def enforce_limit(limiter: KeyedRateLimiter, key: str) -> None:
    retry_after = limiter.hit(key)
    if retry_after is not None:
        raise GameError(
            "auth.rate_limited",
            429,
            headers={"Retry-After": str(math.ceil(retry_after))},
        )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
