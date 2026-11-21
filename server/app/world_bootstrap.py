"""World startup: bind the persistent world row to the generators (docs/world-gen.md).

Shell code (does DB I/O); the generators themselves stay pure in `app.world`.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.worldgen import WorldgenContent
from app.persistence import worldgen_repo as repo
from app.world.generator import WorldGenerator


async def bootstrap_world(
    session: AsyncSession, world_seed: int, content: WorldgenContent
) -> WorldGenerator:
    """Create or check the world row, check pins, pin hand-written names; then commit.

    Raises `WorldSeedMismatch` if WORLD_SEED changed, and `MissingGeneratorVersion` if
    a pin references an unregistered generator version.
    """
    world = await repo.ensure_world(session, world_seed)
    await repo.reconcile_body_name_pins(session)
    await repo.verify_pins(session)
    await session.commit()

    generator = WorldGenerator(world.seed, content, galaxy_version=world.galaxy_version)
    generator.galaxy  # generate now: fail at startup, not on the first request
    return generator
