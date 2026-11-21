"""Initialize (or check) the persistent world in the configured database.

Usage, from the repo root:  poetry run python server/app/cli/init_world.py
Idempotent: safe to run repeatedly. Writes only the `worlds` row and missing pins.
"""

import asyncio
import collections
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow running as a plain script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func, select

from app.config import get_settings
from app.content.worldgen import load_worldgen_content
from app.persistence.db import dispose_engine, get_sessionmaker
from app.persistence.models import BodyName, World, WorldgenPin
from app.world_bootstrap import bootstrap_world


async def main() -> None:
    settings = get_settings()
    content = load_worldgen_content()
    async with get_sessionmaker()() as session:
        generator = await bootstrap_world(
            session, settings.require_world_seed(), content
        )
        world = await session.scalar(select(World).order_by(World.world_id).limit(1))
        pins = await session.scalar(select(func.count()).select_from(WorldgenPin))
        names = await session.scalar(select(func.count()).select_from(BodyName))
    await dispose_engine()

    galaxy = generator.galaxy
    kinds = collections.Counter(link.kind for link in galaxy.links)
    planets = sum(len(generator.system(s.index).slots) for s in galaxy.stars)
    print(
        f"world_id={world.world_id} galaxy_version={world.galaxy_version} "
        f"created_at={world.created_at:%Y-%m-%d %H:%M:%S%z}"
    )
    print(f"pins={pins} custom_names={names}")
    print(
        f"galaxy: {len(galaxy.clusters)} clusters, {len(galaxy.stars)} stars, "
        f"{kinds['lane']} lanes, {kinds['bridge']} bridges, {planets} planets"
    )


if __name__ == "__main__":
    asyncio.run(main())
