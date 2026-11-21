"""Database engine, session factory and declarative base.

Postgres (Supabase) in production, any SQLAlchemy async URL elsewhere (e.g. SQLite in
tests). Game code talks to the DB only through SQLAlchemy — no Supabase SDK.
"""

from collections.abc import AsyncIterator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

# Deterministic constraint names, so Alembic (incl. batch mode on SQLite) can
# reference and drop them reliably.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_ASYNC_DRIVER_PREFIXES = {
    "postgresql://": "postgresql+asyncpg://",
    "postgres://": "postgresql+asyncpg://",
    "sqlite://": "sqlite+aiosqlite://",
}


def normalize_db_url(url: str) -> str:
    """Point driverless URLs at their async driver; leave explicit drivers alone."""
    url = url.strip()
    for prefix, replacement in _ASYNC_DRIVER_PREFIXES.items():
        if url.startswith(prefix):
            return replacement + url[len(prefix) :]
    return url


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(normalize_db_url(url), pool_pre_ping=True)


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Process-wide engine, created lazily from `DATABASE_URL`."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """Close pooled connections; call on application shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
