"""DB access for world-gen deltas: the world row, version pins and custom body names.

Functions never commit: pins must land in the same transaction as the delta that
caused them (docs/world-gen.md "Versioning"), so the caller owns the transaction.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import BodyName, World, WorldgenPin
from app.world import paths, versions

Pins = dict[tuple[str, str], int]  # (object_path, generator) -> version


class WorldSeedMismatch(RuntimeError):
    """WORLD_SEED differs from the seed the persistent world was created with."""


class MissingGeneratorVersion(RuntimeError):
    """A pin references a generator version that is no longer in the registry."""


async def ensure_world(session: AsyncSession, seed: int) -> World:
    """Return the world row, creating it (pinned to the latest galaxy version) on first run."""
    world = await session.scalar(select(World).order_by(World.world_id).limit(1))
    if world is None:
        world = World(seed=seed, galaxy_version=versions.LATEST[versions.GALAXY])
        session.add(world)
        await session.flush()
        return world
    if world.seed != seed:
        raise WorldSeedMismatch(
            f"WORLD_SEED={seed} but the world was created with seed {world.seed}"
        )
    return world


async def load_pins(session: AsyncSession) -> Pins:
    rows = await session.scalars(select(WorldgenPin))
    return {(r.object_path, r.generator): r.version for r in rows}


async def verify_pins(session: AsyncSession) -> Pins:
    """Startup check: every pinned (generator, version) must still be registered."""
    pins = await load_pins(session)
    missing = versions.missing_versions((gen, ver) for (_, gen), ver in pins.items())
    if missing:
        raise MissingGeneratorVersion(
            f"pinned generator versions not registered: {missing}"
        )
    return pins


async def pin_for_delta(session: AsyncSession, generator: str, entity_path: str) -> int:
    """Pin the entity (and its structural dependencies) to the latest versions.

    Call in the same transaction as the delta. Idempotent: existing pins are kept.
    Returns the number of pins created.
    """
    created = 0
    for object_path, gen in versions.pins_for_delta(generator, entity_path):
        if await session.get(WorldgenPin, (object_path, gen)) is None:
            session.add(
                WorldgenPin(
                    object_path=object_path, generator=gen, version=versions.LATEST[gen]
                )
            )
            created += 1
    await session.flush()
    return created


async def set_body_name(session: AsyncSession, planet_path: str, name: str) -> None:
    """Set a planet's custom name (a delta) and pin the planet. For scripts/admin use."""
    paths.parse_planet_path(planet_path)  # validates the path shape
    name = name.strip()
    if not name:
        raise ValueError("custom name must not be blank")
    row = await session.get(BodyName, planet_path)
    if row is None:
        session.add(BodyName(object_path=planet_path, custom_name=name))
    else:
        row.custom_name = name
    await pin_for_delta(session, versions.PLANET, planet_path)


async def get_body_names(
    session: AsyncSession, object_paths: Iterable[str]
) -> dict[str, str]:
    wanted = list(object_paths)
    if not wanted:
        return {}
    rows = await session.scalars(
        select(BodyName).where(BodyName.object_path.in_(wanted))
    )
    return {r.object_path: r.custom_name for r in rows}


async def reconcile_body_name_pins(session: AsyncSession) -> int:
    """Create missing pins for names written directly in the DB. Run at startup."""
    created = 0
    for path in await session.scalars(select(BodyName.object_path)):
        created += await pin_for_delta(session, versions.PLANET, path)
    return created
