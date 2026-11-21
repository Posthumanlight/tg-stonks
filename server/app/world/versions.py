"""Generator version registry and pinning rules. See docs/world-gen.md "Versioning".

Old versions stay registered while any pin references them.
"""

from collections.abc import Callable, Iterable
from typing import Any

from app.world import paths
from app.world.galaxy import v1 as galaxy_v1
from app.world.planet import v1 as planet_v1
from app.world.system import v1 as system_v1

GALAXY = "galaxy"
SYSTEM = "system"
PLANET = "planet"

GENERATORS: dict[str, dict[int, Callable[..., Any]]] = {
    GALAXY: {galaxy_v1.VERSION: galaxy_v1.generate},
    SYSTEM: {system_v1.VERSION: system_v1.generate},
    PLANET: {planet_v1.VERSION: planet_v1.generate},
}
LATEST: dict[str, int] = {name: max(versions) for name, versions in GENERATORS.items()}

# Structural context a generator's output depends on. Pinning an entity also pins these
# (on the matching ancestor object), so the entity's inputs can't shift under it.
DEPENDENCIES: dict[str, tuple[str, ...]] = {
    GALAXY: (),
    SYSTEM: (),
    PLANET: (SYSTEM,),
}


def get_generator(generator: str, version: int) -> Callable[..., Any]:
    try:
        return GENERATORS[generator][version]
    except KeyError:
        raise LookupError(f"generator {generator!r} has no version {version}") from None


def root_path(generator: str, entity_path: str) -> str:
    """Path of the object that `generator` owns, at or above `entity_path`."""
    if generator == GALAXY:
        return paths.GALAXY_PATH
    if generator == SYSTEM:
        try:
            return paths.star_path(paths.parse_star_path(entity_path))
        except LookupError:
            return paths.star_path(paths.parse_planet_path(entity_path).star)
    if generator == PLANET:
        ref = paths.parse_planet_path(entity_path)
        return paths.planet_path(ref.star, ref.planet)
    raise LookupError(f"unknown generator {generator!r}")


def pins_for_delta(generator: str, entity_path: str) -> list[tuple[str, str]]:
    """(object_path, generator) pairs to pin when a delta first touches this entity.

    The entity itself plus its structural dependencies, e.g. a planet delta pins
    ("s/17/p/2", "planet") and ("s/17", "system"). The galaxy is pinned per world
    (worlds.galaxy_version), never through this table.
    """
    if generator == GALAXY:
        raise ValueError("the galaxy is pinned per world, not per object")
    pins = [(root_path(generator, entity_path), generator)]
    pins += [(root_path(dep, entity_path), dep) for dep in DEPENDENCIES[generator]]
    return pins


def missing_versions(pins: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    """(generator, version) pairs referenced by pins but absent from the registry."""
    return sorted(
        {(gen, ver) for gen, ver in pins if ver not in GENERATORS.get(gen, {})}
    )
