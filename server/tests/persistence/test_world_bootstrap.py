from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.content.worldgen import load_worldgen_content
from app.persistence import worldgen_repo as repo
from app.persistence.db import Base, create_engine
from app.persistence.models import BodyName, World, WorldgenPin
from app.world_bootstrap import bootstrap_world


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def test_bootstrap_is_idempotent_and_guards_the_seed(
    session: AsyncSession,
) -> None:
    content = load_worldgen_content()
    session.add(BodyName(object_path="s/3/p/1", custom_name="Hand-set"))
    await session.commit()

    generator = await bootstrap_world(session, 77, content)
    assert generator.world_seed == 77
    assert len(generator.galaxy.stars) == content.galaxy.star_count

    await bootstrap_world(session, 77, content)
    assert await session.scalar(select(func.count()).select_from(World)) == 1
    assert await session.scalar(select(func.count()).select_from(WorldgenPin)) == 2

    with pytest.raises(repo.WorldSeedMismatch):
        await bootstrap_world(session, 78, content)
