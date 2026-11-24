from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.content.worldgen import load_worldgen_content
from app.persistence import worldgen_repo as repo
from app.persistence.db import Base, create_engine
from app.persistence.models import WorldgenPin
from app.persistence.worldgen_snapshot import (
    gen_planet_resources,
    gen_planets,
    gen_snapshot,
    gen_stars,
    is_snapshot_table,
    snapshot_metadata,
    write_snapshot,
)
from app.world_bootstrap import bootstrap_world


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _count(session: AsyncSession, table) -> int:
    return await session.scalar(select(func.count()).select_from(table))


async def test_snapshot_covers_everything_and_is_rewritable(
    session: AsyncSession,
) -> None:
    content = load_worldgen_content()
    await repo.set_body_name(session, "s/0/p/1", "Hand-set")
    await session.commit()
    generator = await bootstrap_world(session, 42, content)
    world = await repo.ensure_world(session, 42)
    pins_before = await _count(session, WorldgenPin)

    counts = await write_snapshot(session, world, generator)
    await session.commit()

    galaxy = generator.galaxy
    planets = sum(len(generator.system(s.index).slots) for s in galaxy.stars)
    assert counts["gen_stars"] == len(galaxy.stars)
    assert counts["gen_links"] == len(galaxy.links)
    assert counts["gen_planets"] == planets
    assert await _count(session, gen_planets) == planets
    assert await _count(session, gen_planet_resources) == planets * len(
        content.resources.categories
    )

    named = (
        await session.execute(
            select(gen_planets.c.name, gen_planets.c.has_custom_name).where(
                gen_planets.c.path == "s/0/p/1"
            )
        )
    ).one_or_none()
    if generator.system(0).slots:
        assert named == ("Hand-set", True)

    # Rewriting replaces rows instead of duplicating them, and pins nothing.
    await write_snapshot(session, world, generator)
    await session.commit()
    assert await _count(session, gen_stars) == len(galaxy.stars)
    assert await _count(session, gen_snapshot) == 1
    assert await _count(session, WorldgenPin) == pins_before


def test_snapshot_tables_are_separate_from_game_schema() -> None:
    assert all(is_snapshot_table(name) for name in snapshot_metadata.tables)
    assert not any(is_snapshot_table(name) for name in Base.metadata.tables)
