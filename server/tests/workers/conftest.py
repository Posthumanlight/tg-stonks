from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.combat.ground.ruleset import CombatRuleset, load_ruleset
from app.combat.ground.serialize import setup_to_json
from app.combat.ground.setup import load_demo_setup
from app.persistence.combat_repo import CombatStore
from app.persistence.db import Base, create_engine
from app.persistence.models import User


@pytest.fixture(scope="session")
def ruleset() -> CombatRuleset:
    return load_ruleset()


@pytest.fixture(scope="session")
def demo_setup_json(ruleset: CombatRuleset) -> dict:
    return setup_to_json(load_demo_setup(ruleset))


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'combat.db').as_posix()}"


@pytest.fixture
async def store(db_url: str) -> AsyncIterator[CombatStore]:
    engine = create_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:  # combats reference users
        session.add_all(
            User(
                user_id=uid,
                username=f"u{uid}",
                username_normalized=f"u{uid}",
                hashed_password="x",
            )
            for uid in (1, 2)
        )
        await session.commit()
    yield CombatStore(sessions)
    await engine.dispose()
