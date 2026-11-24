"""Refresh tokens: opaque, stored hashed, rotated on every use, with reuse detection.

A token that was already rotated being presented again means it was copied: the whole
family (one device session) is revoked. Exception: within `RACE_GRACE_S` of rotation,
a second presentation is treated as two tabs refreshing at once — rejected, but the
family survives, and the losing tab retries with the new cookie the winner received.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from app.persistence.auth_repo import RefreshStore
from app.shared.clock import Clock
from app.shared.errors import GameError

RACE_GRACE_S = 10


@dataclass(frozen=True, slots=True)
class IssuedRefresh:
    raw: str  # goes into the cookie, never stored
    family_id: str
    expires_at: float


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _invalid() -> GameError:
    return GameError("auth.invalid_refresh", 401)


class RefreshService:
    def __init__(self, store: RefreshStore, *, ttl_s: int, clock: Clock) -> None:
        self._store = store
        self._ttl = ttl_s
        self._clock = clock

    async def issue(self, user_id: int) -> IssuedRefresh:
        """Start a new family (a new device session)."""
        now = self._clock.now()
        raw, family = secrets.token_urlsafe(32), str(uuid.uuid4())
        await self._store.add(user_id, family, hash_token(raw), now, now + self._ttl)
        return IssuedRefresh(raw, family, now + self._ttl)

    async def rotate(self, raw: str) -> tuple[int, IssuedRefresh]:
        """Exchange a refresh token for its successor. Returns (user_id, new token)."""
        now = self._clock.now()
        record = await self._store.find(hash_token(raw))
        if record is None or record.expires_at <= now:
            raise _invalid()
        if record.revoked_at is not None:
            if (
                record.replaced_by_id is not None
                and now - record.revoked_at <= RACE_GRACE_S
            ):
                raise GameError("auth.refresh_race", 409)
            await self._store.revoke_family(record.family_id, now)  # reuse: theft
            raise _invalid()
        new_raw = secrets.token_urlsafe(32)
        rotated = await self._store.rotate(
            record.token_id,
            record.family_id,
            record.user_id,
            hash_token(new_raw),
            now,
            now + self._ttl,
        )
        if not rotated:
            raise GameError("auth.refresh_race", 409)
        return record.user_id, IssuedRefresh(new_raw, record.family_id, now + self._ttl)

    async def revoke(self, raw: str) -> None:
        record = await self._store.find(hash_token(raw))
        if record is not None:
            await self._store.revoke_family(record.family_id, self._clock.now())

    async def revoke_session(self, family_id: str) -> None:
        await self._store.revoke_family(family_id, self._clock.now())

    async def revoke_all(self, user_id: int) -> None:
        await self._store.revoke_user(user_id, self._clock.now())

    async def cleanup(self) -> int:
        return await self._store.delete_expired(self._clock.now())
