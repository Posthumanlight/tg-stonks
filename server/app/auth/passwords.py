"""Password hashing: argon2id, run in a thread pool so logins never stall the loop
(argon2-cffi releases the GIL)."""

from typing import Protocol

import anyio
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class PasswordHasher(Protocol):
    async def hash(self, password: str) -> str: ...

    async def verify(self, password_hash: str, password: str) -> bool: ...

    async def verify_dummy(self, password: str) -> None:
        """Spend the same time as a real verify (unknown-user path)."""
        ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class Argon2Hasher:
    """argon2id with argon2-cffi's defaults (RFC 9106 low-memory profile) unless
    overridden (tests pass cheap parameters)."""

    def __init__(self, **params: int) -> None:
        self._argon2 = _Argon2(**params)
        self._dummy: str | None = None

    async def hash(self, password: str) -> str:
        return await anyio.to_thread.run_sync(self._argon2.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        def check() -> bool:
            try:
                return self._argon2.verify(password_hash, password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False

        return await anyio.to_thread.run_sync(check)

    async def verify_dummy(self, password: str) -> None:
        if self._dummy is None:
            self._dummy = await self.hash("dummy-password-for-timing")
        await self.verify(self._dummy, password)

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._argon2.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True
