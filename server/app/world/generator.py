"""Facade over the versioned generators, with in-memory caching. Still pure.

Version resolution (which version an object uses) needs pins from the DB; the caller
looks them up and passes versions in. `None` means "not pinned" -> latest.
"""

from functools import cached_property, lru_cache

from app.content.worldgen import WorldgenContent
from app.world import versions
from app.world.errors import UnknownObject
from app.world.types import Galaxy, Planet, SystemSkeleton


class WorldGenerator:
    def __init__(
        self,
        world_seed: int,
        content: WorldgenContent,
        galaxy_version: int = versions.LATEST[versions.GALAXY],
        cache_size: int = 1024,
    ) -> None:
        self.world_seed = world_seed
        self.content = content
        self.galaxy_version = galaxy_version
        self._system = lru_cache(maxsize=cache_size)(self._generate_system)
        self._planet = lru_cache(maxsize=cache_size)(self._generate_planet)

    @cached_property
    def galaxy(self) -> Galaxy:
        generate = versions.get_generator(versions.GALAXY, self.galaxy_version)
        return generate(self.world_seed, self.content)

    def system(self, star_index: int, version: int | None = None) -> SystemSkeleton:
        if not 0 <= star_index < len(self.galaxy.stars):
            raise UnknownObject(f"no star {star_index}")
        return self._system(star_index, version or versions.LATEST[versions.SYSTEM])

    def planet(
        self,
        star_index: int,
        planet_index: int,
        version: int | None = None,
        system_version: int | None = None,
    ) -> Planet:
        skeleton = self.system(star_index, system_version)
        if not 1 <= planet_index <= len(skeleton.slots):
            raise UnknownObject(f"{skeleton.path} has no planet {planet_index}")
        return self._planet(
            star_index,
            planet_index,
            version or versions.LATEST[versions.PLANET],
            skeleton.version,
        )

    def _generate_system(self, star_index: int, version: int) -> SystemSkeleton:
        generate = versions.get_generator(versions.SYSTEM, version)
        return generate(self.world_seed, star_index, self.content)

    def _generate_planet(
        self, star_index: int, planet_index: int, version: int, system_version: int
    ) -> Planet:
        skeleton = self._system(star_index, system_version)
        generate = versions.get_generator(versions.PLANET, version)
        return generate(self.world_seed, skeleton, planet_index, self.content)
