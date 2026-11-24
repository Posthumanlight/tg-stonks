"""Narrow async stores for users and refresh tokens. Each call is one transaction."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.models import RefreshToken, User


class UsernameTaken(Exception):
    pass


@dataclass(frozen=True, slots=True)
class UserRecord:
    user_id: int
    username: str
    role: str
    password_hash: str


@dataclass(frozen=True, slots=True)
class RefreshRecord:
    token_id: int
    user_id: int
    family_id: str
    expires_at: float  # unix seconds
    revoked_at: float | None
    replaced_by_id: int | None


def to_datetime(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, UTC)


def to_timestamp(value: datetime) -> float:
    # SQLite hands back naive datetimes; everything is stored in UTC.
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()


def _user(row: User) -> UserRecord:
    return UserRecord(row.user_id, row.username, row.role, row.hashed_password)


class UserStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self, username: str, normalized: str, password_hash: str
    ) -> UserRecord:
        async with self._sessions() as session:
            row = User(
                username=username,
                username_normalized=normalized,
                hashed_password=password_hash,
                role="player",
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                raise UsernameTaken(username) from exc
            await session.refresh(row)
            return _user(row)

    async def by_normalized_name(self, normalized: str) -> UserRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(User).where(User.username_normalized == normalized)
            )
            return _user(row) if row else None

    async def get(self, user_id: int) -> UserRecord | None:
        async with self._sessions() as session:
            row = await session.get(User, user_id)
            return _user(row) if row else None

    async def set_password_hash(self, user_id: int, password_hash: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(User)
                .where(User.user_id == user_id)
                .values(hashed_password=password_hash)
            )
            await session.commit()


def _refresh(row: RefreshToken) -> RefreshRecord:
    return RefreshRecord(
        token_id=row.token_id,
        user_id=row.user_id,
        family_id=str(row.family_id),
        expires_at=to_timestamp(row.expires_at),
        revoked_at=to_timestamp(row.revoked_at) if row.revoked_at else None,
        replaced_by_id=row.replaced_by_id,
    )


class RefreshStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def _row(
        user_id: int, family_id: str, token_hash: str, now: float, expires: float
    ) -> RefreshToken:
        return RefreshToken(
            user_id=user_id,
            family_id=uuid.UUID(family_id),
            token_hash=token_hash,
            created_at=to_datetime(now),
            expires_at=to_datetime(expires),
        )

    async def add(
        self, user_id: int, family_id: str, token_hash: str, now: float, expires: float
    ) -> None:
        async with self._sessions() as session:
            session.add(self._row(user_id, family_id, token_hash, now, expires))
            await session.commit()

    async def find(self, token_hash: str) -> RefreshRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash)
            )
            return _refresh(row) if row else None

    async def rotate(
        self,
        old_token_id: int,
        family_id: str,
        user_id: int,
        new_hash: str,
        now: float,
        expires: float,
    ) -> bool:
        """Revoke the old token and add its successor atomically. False if the old token
        was revoked concurrently (someone else rotated it first)."""
        async with self._sessions() as session:
            new = self._row(user_id, family_id, new_hash, now, expires)
            session.add(new)
            await session.flush()
            result = await session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.token_id == old_token_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=to_datetime(now), replaced_by_id=new.token_id)
            )
            if result.rowcount != 1:
                await session.rollback()
                return False
            await session.commit()
            return True

    async def revoke_family(self, family_id: str, now: float) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == uuid.UUID(family_id),
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=to_datetime(now))
            )
            await session.commit()

    async def revoke_user(self, user_id: int, now: float) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
                )
                .values(revoked_at=to_datetime(now))
            )
            await session.commit()

    async def delete_expired(self, now: float) -> int:
        async with self._sessions() as session:
            result = await session.execute(
                delete(RefreshToken).where(RefreshToken.expires_at < to_datetime(now))
            )
            await session.commit()
            return result.rowcount or 0
