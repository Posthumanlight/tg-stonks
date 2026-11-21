from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persistence import worldgen_repo as repo
from app.persistence.db import Base, create_engine
from app.persistence.models import BodyName, WorldgenPin
from app.world import versions


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def test_ensure_world_creates_then_checks_seed(session: AsyncSession) -> None:
    world = await repo.ensure_world(session, 123)
    assert world.seed == 123
    assert world.galaxy_version == versions.LATEST[versions.GALAXY]
    await session.commit()

    assert (await repo.ensure_world(session, 123)).world_id == world.world_id
    with pytest.raises(repo.WorldSeedMismatch):
        await repo.ensure_world(session, 124)


async def test_pin_for_delta_is_idempotent(session: AsyncSession) -> None:
    assert await repo.pin_for_delta(session, versions.PLANET, "s/17/p/2") == 2
    assert await repo.pin_for_delta(session, versions.PLANET, "s/17/p/2") == 0
    # A sibling planet shares the already-pinned system skeleton.
    assert await repo.pin_for_delta(session, versions.PLANET, "s/17/p/3") == 1
    await session.commit()

    assert await repo.load_pins(session) == {
        ("s/17/p/2", "planet"): 1,
        ("s/17/p/3", "planet"): 1,
        ("s/17", "system"): 1,
    }


async def test_set_body_name_pins_planet(session: AsyncSession) -> None:
    await repo.set_body_name(session, "s/5/p/1", "  New Hope ")
    await repo.set_body_name(session, "s/5/p/1", "Newer Hope")
    await session.commit()

    assert await repo.get_body_names(session, ["s/5/p/1", "s/5/p/2"]) == {
        "s/5/p/1": "Newer Hope"
    }
    pins = await repo.load_pins(session)
    assert set(pins) == {("s/5/p/1", "planet"), ("s/5", "system")}

    with pytest.raises(LookupError):
        await repo.set_body_name(session, "s/5", "A star")
    with pytest.raises(ValueError):
        await repo.set_body_name(session, "s/5/p/1", "   ")


async def test_reconcile_pins_names_written_directly(session: AsyncSession) -> None:
    session.add(BodyName(object_path="s/9/p/4", custom_name="Hand-set"))
    await session.commit()

    assert await repo.reconcile_body_name_pins(session) == 2
    assert await repo.reconcile_body_name_pins(session) == 0
    await session.commit()
    assert await session.scalar(select(func.count()).select_from(WorldgenPin)) == 2


async def test_verify_pins_rejects_unregistered_versions(session: AsyncSession) -> None:
    session.add(WorldgenPin(object_path="s/1/p/1", generator="planet", version=1))
    await session.commit()
    assert await repo.verify_pins(session) == {("s/1/p/1", "planet"): 1}

    session.add(WorldgenPin(object_path="s/2/p/1", generator="planet", version=99))
    await session.commit()
    with pytest.raises(repo.MissingGeneratorVersion):
        await repo.verify_pins(session)
