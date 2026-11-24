import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

import app.persistence.models  # noqa: F401  (registers all tables on Base.metadata)
from app.config import get_settings
from app.persistence.db import Base, normalize_db_url
from app.persistence.worldgen_snapshot import is_snapshot_table

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # Read straight from settings rather than via config.set_main_option: ConfigParser
    # interpolation would choke on '%' in URL-encoded passwords.
    return normalize_db_url(get_settings().database_url)


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep the debug `gen_*` snapshot tables out of autogenerate (no drop proposals)."""
    table = (
        name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
    )
    return not is_snapshot_table(table)


def _configure_kwargs() -> dict:
    return {
        "target_metadata": target_metadata,
        "render_as_batch": True,
        "compare_type": True,
        "include_object": _include_object,
    }


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (`alembic upgrade head --sql`)."""
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_kwargs(),
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, **_configure_kwargs())

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(_database_url(), poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
