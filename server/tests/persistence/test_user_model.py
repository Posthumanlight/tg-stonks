from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence.db import Base, create_engine, normalize_db_url
from app.persistence.models import User


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def test_insert_assigns_user_id(session: AsyncSession) -> None:
    first = User(username="alice", hashed_password="hash-a")
    second = User(username="bob", hashed_password="hash-b")
    session.add_all([first, second])
    await session.commit()

    assert isinstance(first.user_id, int)
    assert second.user_id != first.user_id

    loaded = await session.scalar(select(User).where(User.username == "alice"))
    assert loaded is not None
    assert loaded.hashed_password == "hash-a"


async def test_username_is_unique(session: AsyncSession) -> None:
    session.add(User(username="alice", hashed_password="hash-a"))
    await session.commit()

    session.add(User(username="alice", hashed_password="hash-b"))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgresql://u:p@host:5432/postgres",
            "postgresql+asyncpg://u:p@host:5432/postgres",
        ),
        ("postgres://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        (
            "postgresql+asyncpg://u:p@host/db",
            "postgresql+asyncpg://u:p@host/db",
        ),
        ("sqlite:///:memory:", "sqlite+aiosqlite:///:memory:"),
        ("  postgresql://u:p@host/db\n", "postgresql+asyncpg://u:p@host/db"),
    ],
)
def test_normalize_db_url(raw: str, expected: str) -> None:
    assert normalize_db_url(raw) == expected
