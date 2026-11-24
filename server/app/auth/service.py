"""Account flows: register, login, refresh, logout. HTTP-agnostic (routes stay thin)."""

from dataclasses import dataclass

from app.auth import rules
from app.auth.passwords import PasswordHasher
from app.auth.refresh import IssuedRefresh, RefreshService
from app.auth.tokens import AccessToken, TokenService
from app.persistence.auth_repo import UserRecord, UsernameTaken, UserStore
from app.shared.errors import GameError


@dataclass(frozen=True, slots=True)
class Session:
    user: UserRecord
    access: AccessToken
    refresh: IssuedRefresh


def _invalid_credentials() -> GameError:
    return GameError("auth.invalid_credentials", 401)


class AuthService:
    def __init__(
        self,
        users: UserStore,
        refresh: RefreshService,
        tokens: TokenService,
        hasher: PasswordHasher,
    ) -> None:
        self.users = users
        self.refresh_tokens = refresh
        self.tokens = tokens
        self.hasher = hasher

    async def register(self, username: str, password: str) -> UserRecord:
        username = rules.check_username(username)
        rules.check_password(password)
        password_hash = await self.hasher.hash(password)
        try:
            return await self.users.create(
                username, rules.normalize_username(username), password_hash
            )
        except UsernameTaken as exc:
            raise GameError("auth.username_taken", 409) from exc

    async def login(self, username: str, password: str) -> Session:
        user = await self.users.by_normalized_name(rules.normalize_username(username))
        if user is None or len(password) > rules.PASSWORD_MAX:
            await self.hasher.verify_dummy(password[: rules.PASSWORD_MAX])
            raise _invalid_credentials()
        if not await self.hasher.verify(user.password_hash, password):
            raise _invalid_credentials()
        if self.hasher.needs_rehash(user.password_hash):
            await self.users.set_password_hash(
                user.user_id, await self.hasher.hash(password)
            )
        return await self._session(user, await self.refresh_tokens.issue(user.user_id))

    async def refresh(self, raw: str) -> Session:
        user_id, issued = await self.refresh_tokens.rotate(raw)
        user = await self.users.get(user_id)
        if user is None:
            raise GameError("auth.invalid_refresh", 401)
        return await self._session(user, issued)

    async def logout(self, raw: str | None) -> None:
        if raw:
            await self.refresh_tokens.revoke(raw)

    async def logout_all(self, user_id: int) -> None:
        await self.refresh_tokens.revoke_all(user_id)

    async def _session(self, user: UserRecord, issued: IssuedRefresh) -> Session:
        access = self.tokens.issue(user.user_id, user.role, issued.family_id)
        return Session(user, access, issued)
