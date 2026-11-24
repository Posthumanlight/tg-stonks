"""Debug snapshot of the whole generated world, for browsing it in a DB UI (Supabase).

NOT part of the game's state. Rule 4 (procgen = seed + deltas) still holds: the game
never reads these tables, they are wiped and rebuilt from the generators on every
snapshot, and taking a snapshot pins nothing. Tables live on their own MetaData (not
`Base`), are created by the snapshot script rather than Alembic, and are excluded from
autogenerate in `migrations/env.py`. Dropping them at any time loses nothing.
"""

from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence import worldgen_repo as repo
from app.persistence.db import NAMING_CONVENTION
from app.persistence.models import World
from app.persistence.models.world import PATH_LENGTH
from app.world import paths, versions
from app.world.generator import WorldGenerator
from app.world.naming import planet_display_name
from app.world.system.v1 import frost_line_mau, habitable_zone_mau

TABLE_PREFIX = "gen_"

snapshot_metadata = MetaData(naming_convention=NAMING_CONVENTION)

gen_snapshot = Table(
    "gen_snapshot",
    snapshot_metadata,
    Column("snapshot_id", Integer, primary_key=True, autoincrement=False),
    Column("world_id", BigInteger, nullable=False),
    Column("world_seed", BigInteger, nullable=False),
    Column("galaxy_version", Integer, nullable=False),
    Column("latest_system_version", Integer, nullable=False),
    Column("latest_planet_version", Integer, nullable=False),
    Column("clusters", Integer, nullable=False),
    Column("stars", Integer, nullable=False),
    Column("links", Integer, nullable=False),
    Column("planets", Integer, nullable=False),
    Column("taken_at", DateTime(timezone=True), server_default=func.now()),
)

gen_clusters = Table(
    "gen_clusters",
    snapshot_metadata,
    Column("cluster_index", Integer, primary_key=True, autoincrement=False),
    Column("path", String(PATH_LENGTH), nullable=False),
    Column("code", String(16), nullable=False),
    Column("name", String(64), nullable=False),
    Column("x", Integer, nullable=False),
    Column("y", Integer, nullable=False),
    Column("radius", Integer, nullable=False),
    Column("star_count", Integer, nullable=False),
)

gen_stars = Table(
    "gen_stars",
    snapshot_metadata,
    Column("star_index", Integer, primary_key=True, autoincrement=False),
    Column("path", String(PATH_LENGTH), nullable=False),
    Column("code", String(16), nullable=False),
    Column("name", String(64), nullable=False),
    Column("cluster_index", Integer, nullable=False),
    Column("cluster_name", String(64), nullable=False),
    Column("x", Integer, nullable=False),
    Column("y", Integer, nullable=False),
    Column("link_count", Integer, nullable=False),
    Column("system_version", Integer, nullable=False),
    Column("spectral_type", String(8), nullable=False),
    Column("star_class", String(4), nullable=False),
    Column("subclass", Integer, nullable=False),
    Column("temperature_k", Integer, nullable=False),
    Column("luminosity_mlsun", BigInteger, nullable=False),
    Column("radius_milli_rsun", BigInteger, nullable=False),
    Column("colour", String(16), nullable=False),
    Column("planet_count", Integer, nullable=False),
    Column("hz_inner_mau", BigInteger, nullable=False),
    Column("hz_outer_mau", BigInteger, nullable=False),
    Column("frost_line_mau", BigInteger, nullable=False),
)

gen_links = Table(
    "gen_links",
    snapshot_metadata,
    Column("star_a", Integer, primary_key=True, autoincrement=False),
    Column("star_b", Integer, primary_key=True, autoincrement=False),
    Column("name_a", String(64), nullable=False),
    Column("name_b", String(64), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("length", Integer, nullable=False),
)

gen_planets = Table(
    "gen_planets",
    snapshot_metadata,
    Column("path", String(PATH_LENGTH), primary_key=True),
    Column("code", String(16), nullable=False),
    Column("name", String(64), nullable=False),
    Column("has_custom_name", Boolean, nullable=False),
    Column("star_index", Integer, nullable=False),
    Column("star_name", String(64), nullable=False),
    Column("planet_index", Integer, nullable=False),
    Column("planet_version", Integer, nullable=False),
    Column("planet_type", String(32), nullable=False),
    Column("size_class", String(16), nullable=False),
    Column("temp_bucket", String(16), nullable=False),
    Column("temperature_k", Integer, nullable=False),
    Column("in_habitable_zone", Boolean, nullable=False),
    Column("atmosphere", String(32), nullable=False),
    Column("landable", Boolean, nullable=False),
    Column("surface_n", Integer, nullable=True),
    Column("radius_km", Integer, nullable=False),
    Column("gravity_mg", Integer, nullable=False),
    Column("orbit_mau", BigInteger, nullable=False),
    Column("x_mau", BigInteger, nullable=False),
    Column("y_mau", BigInteger, nullable=False),
    Column("resources", JSON, nullable=False),
)

gen_planet_resources = Table(
    "gen_planet_resources",
    snapshot_metadata,
    Column("planet_path", String(PATH_LENGTH), primary_key=True),
    Column("category", String(32), primary_key=True),
    Column("abundance", Integer, nullable=False),
)

# Delete order (no FKs, but keep children before parents for readability).
SNAPSHOT_TABLES = (
    gen_planet_resources,
    gen_planets,
    gen_links,
    gen_stars,
    gen_clusters,
    gen_snapshot,
)


def is_snapshot_table(name: str | None) -> bool:
    return bool(name) and name.startswith(TABLE_PREFIX)


def build_snapshot_rows(
    generator: WorldGenerator,
    pins: repo.Pins,
    custom_names: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Generate every object (respecting pins) and flatten it into table rows. Pure."""
    galaxy = generator.galaxy
    degree = [0] * len(galaxy.stars)
    for link in galaxy.links:
        degree[link.a] += 1
        degree[link.b] += 1

    clusters = [
        {
            "cluster_index": c.index,
            "path": c.path,
            "code": c.code,
            "name": c.name,
            "x": c.x,
            "y": c.y,
            "radius": c.radius,
            "star_count": len(c.stars),
        }
        for c in galaxy.clusters
    ]
    links = [
        {
            "star_a": link.a,
            "star_b": link.b,
            "name_a": galaxy.stars[link.a].name,
            "name_b": galaxy.stars[link.b].name,
            "kind": link.kind,
            "length": link.length,
        }
        for link in galaxy.links
    ]

    stars: list[dict[str, Any]] = []
    planets: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    for star in galaxy.stars:
        system_version = pins.get((star.path, versions.SYSTEM))
        skeleton = generator.system(star.index, system_version)
        props = skeleton.star
        hz_inner, hz_outer = habitable_zone_mau(props.luminosity_mlsun)
        stars.append(
            {
                "star_index": star.index,
                "path": star.path,
                "code": star.code,
                "name": star.name,
                "cluster_index": star.cluster,
                "cluster_name": galaxy.clusters[star.cluster].name,
                "x": star.x,
                "y": star.y,
                "link_count": degree[star.index],
                "system_version": skeleton.version,
                "spectral_type": f"{props.star_class}{props.subclass}V",
                "star_class": props.star_class,
                "subclass": props.subclass,
                "temperature_k": props.temperature_k,
                "luminosity_mlsun": props.luminosity_mlsun,
                "radius_milli_rsun": props.radius_milli_rsun,
                "colour": props.colour,
                "planet_count": len(skeleton.slots),
                "hz_inner_mau": hz_inner,
                "hz_outer_mau": hz_outer,
                "frost_line_mau": frost_line_mau(props.luminosity_mlsun),
            }
        )
        for slot in skeleton.slots:
            planet = generator.planet(
                star.index,
                slot.index,
                pins.get((slot.path, versions.PLANET)),
                system_version,
            )
            custom = custom_names.get(planet.path)
            planets.append(
                {
                    "path": planet.path,
                    "code": planet.code,
                    "name": planet_display_name(star.name, planet.index, custom),
                    "has_custom_name": custom is not None,
                    "star_index": star.index,
                    "star_name": star.name,
                    "planet_index": planet.index,
                    "planet_version": planet.version,
                    "planet_type": planet.planet_type,
                    "size_class": planet.size_class,
                    "temp_bucket": planet.temp_bucket,
                    "temperature_k": planet.temperature_k,
                    "in_habitable_zone": planet.in_habitable_zone,
                    "atmosphere": planet.atmosphere,
                    "landable": planet.landable,
                    "surface_n": planet.surface_n,
                    "radius_km": planet.radius_km,
                    "gravity_mg": planet.gravity_mg,
                    "orbit_mau": planet.orbit_mau,
                    "x_mau": planet.x_mau,
                    "y_mau": planet.y_mau,
                    "resources": dict(planet.resources),
                }
            )
            resources.extend(
                {"planet_path": planet.path, "category": cat, "abundance": value}
                for cat, value in planet.resources.items()
            )

    return {
        gen_clusters.name: clusters,
        gen_stars.name: stars,
        gen_links.name: links,
        gen_planets.name: planets,
        gen_planet_resources.name: resources,
    }


async def write_snapshot(
    session: AsyncSession, world: World, generator: WorldGenerator
) -> dict[str, int]:
    """Create the snapshot tables if needed and replace their contents. Doesn't commit.

    Returns the row count per table.
    """
    pins = await repo.load_pins(session)
    custom_names = await repo.get_body_names(
        session,
        (
            paths.planet_path(star.index, slot.index)
            for star in generator.galaxy.stars
            for slot in generator.system(
                star.index, pins.get((star.path, versions.SYSTEM))
            ).slots
        ),
    )
    rows = build_snapshot_rows(generator, pins, custom_names)

    connection = await session.connection()
    await connection.run_sync(snapshot_metadata.create_all)
    for table in SNAPSHOT_TABLES:
        await session.execute(table.delete())
    for table in reversed(SNAPSHOT_TABLES):
        table_rows = rows.get(table.name)
        if table_rows:
            await session.execute(table.insert(), table_rows)

    counts = {name: len(table_rows) for name, table_rows in rows.items()}
    await session.execute(
        gen_snapshot.insert(),
        [
            {
                "snapshot_id": 1,
                "world_id": world.world_id,
                "world_seed": world.seed,
                "galaxy_version": generator.galaxy_version,
                "latest_system_version": versions.LATEST[versions.SYSTEM],
                "latest_planet_version": versions.LATEST[versions.PLANET],
                "clusters": counts[gen_clusters.name],
                "stars": counts[gen_stars.name],
                "links": counts[gen_links.name],
                "planets": counts[gen_planets.name],
            }
        ],
    )
    counts[gen_snapshot.name] = 1
    return counts
