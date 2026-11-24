"""Write the whole generated galaxy into `gen_*` debug tables, to browse it in Supabase.

Usage, from the repo root:  poetry run python server/app/cli/snapshot_world.py

Generates every cluster, star, link and planet (as if all were visited) and replaces the
contents of the snapshot tables. These tables are a read-only view for humans: the game
never reads them, nothing gets pinned, and re-running after a content/generator change
simply refreshes them. See app/persistence/worldgen_snapshot.py.
"""

import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow running as a plain script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_settings
from app.content.worldgen import load_worldgen_content
from app.persistence import worldgen_repo as repo
from app.persistence.db import dispose_engine, get_sessionmaker
from app.persistence.worldgen_snapshot import write_snapshot
from app.world_bootstrap import bootstrap_world


async def main() -> None:
    settings = get_settings()
    content = load_worldgen_content()
    try:
        async with get_sessionmaker()() as session:
            generator = await bootstrap_world(
                session, settings.require_world_seed(), content
            )
            world = await repo.ensure_world(session, generator.world_seed)
            counts = await write_snapshot(session, world, generator)
            await session.commit()
    finally:
        await dispose_engine()

    print(f"snapshot of world_id={world.world_id} (seed {world.seed}) written:")
    for table, count in sorted(counts.items()):
        print(f"  {table:<22} {count:>6} rows")


if __name__ == "__main__":
    asyncio.run(main())
