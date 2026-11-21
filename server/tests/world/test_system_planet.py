"""System skeleton v1 and planet v1 invariants."""

import math

import pytest

from app.content.worldgen import WorldgenContent
from app.world.errors import UnknownObject
from app.world.generator import WorldGenerator
from app.world.planet import v1 as planet_v1
from app.world.system import v1 as system_v1
from app.world.types import Planet, SystemSkeleton

SEED = 1234


@pytest.fixture(scope="module")
def world(content: WorldgenContent) -> WorldGenerator:
    return WorldGenerator(SEED, content)


@pytest.fixture(scope="module")
def systems(world: WorldGenerator) -> list[SystemSkeleton]:
    return [world.system(s) for s in range(len(world.galaxy.stars))]


@pytest.fixture(scope="module")
def planets(world: WorldGenerator, systems: list[SystemSkeleton]) -> list[Planet]:
    return [
        world.planet(sk.star_index, slot.index) for sk in systems for slot in sk.slots
    ]


def test_star_properties(
    systems: list[SystemSkeleton], content: WorldgenContent
) -> None:
    for sk in systems:
        star = sk.star
        cls = content.stars.classes[star.star_class]
        assert 0 <= star.subclass <= 9
        assert cls.temperature_k[0] <= star.temperature_k <= cls.temperature_k[1]
        low, high = cls.luminosity_lsun
        assert round(low * 1000) - 1 <= star.luminosity_mlsun <= round(high * 1000) + 1
        assert star.colour == cls.colour


def test_hotter_subclass_is_brighter(content: WorldgenContent) -> None:
    # Within one class, subclass 0 sits at the hot end: compare extremes over many stars.
    by_class: dict[str, list[tuple[int, int]]] = {}
    for s in range(400):
        star = system_v1.generate(99, s, content).star
        by_class.setdefault(star.star_class, []).append(
            (star.subclass, star.temperature_k)
        )
    for entries in by_class.values():
        hot = [t for sub, t in entries if sub == 0]
        cool = [t for sub, t in entries if sub == 9]
        if hot and cool:
            assert min(hot) > max(cool)


def test_slots(systems: list[SystemSkeleton]) -> None:
    for sk in systems:
        assert 0 <= len(sk.slots) <= system_v1.MAX_PLANETS
        orbits = [slot.orbit_mau for slot in sk.slots]
        assert orbits == sorted(orbits) and len(set(orbits)) == len(orbits)
        for i, slot in enumerate(sk.slots, start=1):
            assert slot.index == i
            assert slot.path == f"{sk.path}/p/{i}"
            assert abs(math.hypot(slot.x_mau, slot.y_mau) - slot.orbit_mau) <= 1.5


def test_planets(planets: list[Planet], content: WorldgenContent) -> None:
    pc = content.planets
    categories = [c.id for c in content.resources.categories]
    assert planets, "seed should produce some planets"
    for p in planets:
        ptype = pc.types[p.planet_type]
        assert ptype.allows(p.temperature_k, p.size_class)
        low, high = pc.size_classes[p.size_class].radius_km
        assert low <= p.radius_km <= high
        assert p.landable == ptype.landable
        if p.landable:
            assert p.surface_n == pc.size_classes[p.size_class].surface_n
        else:
            assert p.surface_n is None
        assert list(p.resources) == categories
        assert all(0 <= v <= 100 for v in p.resources.values())
        for category, value in p.resources.items():
            if category not in ptype.resources:
                assert value == 0


def test_temperature_falls_with_orbit(
    world: WorldGenerator, systems: list[SystemSkeleton]
) -> None:
    for sk in systems:
        temps = [world.planet(sk.star_index, s.index).temperature_k for s in sk.slots]
        assert temps == sorted(temps, reverse=True)


def test_giants_are_never_landable(planets: list[Planet]) -> None:
    assert all(not p.landable for p in planets if p.size_class == "giant")


def test_planet_generation_is_deterministic(
    content: WorldgenContent, systems: list[SystemSkeleton]
) -> None:
    sk = next(sk for sk in systems if sk.slots)
    a = planet_v1.generate(SEED, sk, 1, content)
    b = planet_v1.generate(
        SEED, system_v1.generate(SEED, sk.star_index, content), 1, content
    )
    assert a == b


def test_unknown_objects(world: WorldGenerator, systems: list[SystemSkeleton]) -> None:
    with pytest.raises(UnknownObject):
        world.system(len(systems))
    sk = systems[0]
    with pytest.raises(UnknownObject):
        world.planet(sk.star_index, len(sk.slots) + 1)
    with pytest.raises(UnknownObject):
        world.planet(sk.star_index, 0)


def test_unregistered_version_is_rejected(world: WorldGenerator) -> None:
    with pytest.raises(LookupError):
        world.system(0, version=999)
