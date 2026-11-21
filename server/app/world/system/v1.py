"""System skeleton generator v1: the star and its planet slots (orbits, static positions).

See docs/world-gen.md "Star systems". Root object: `s/<star>`.
"""

import math
import random

from app.content.worldgen import WorldgenContent
from app.world import paths
from app.world.seeds import make_rng
from app.world.types import PlanetSlot, StarProps, SystemSkeleton

VERSION = 1
MAX_PLANETS = 8


def generate(
    world_seed: int, star_index: int, content: WorldgenContent
) -> SystemSkeleton:
    path = paths.star_path(star_index)
    star = _star(make_rng(world_seed, path, "star"), content)
    slots = _slots(make_rng(world_seed, path, "slots"), star_index, star, content)
    return SystemSkeleton(
        version=VERSION, star_index=star_index, path=path, star=star, slots=slots
    )


def _lerp(bounds: tuple[float, float], t: float) -> float:
    return bounds[0] + t * (bounds[1] - bounds[0])


def _fourth_root(x: float) -> float:
    return math.sqrt(math.sqrt(x))


def _star(rng: random.Random, content: WorldgenContent) -> StarProps:
    classes = list(content.stars.classes.items())
    class_id, star_class = rng.choices(classes, weights=[c.weight for _, c in classes])[
        0
    ]
    subclass = rng.randrange(10)
    t = (9 - subclass + rng.random()) / 10  # 1 = hot end of the class

    # Luminosity spans orders of magnitude: interpolate in fourth-root space.
    low, high = star_class.luminosity_lsun
    q = _lerp((_fourth_root(low), _fourth_root(high)), t)
    luminosity = q * q * q * q

    return StarProps(
        star_class=class_id,
        subclass=subclass,
        temperature_k=round(_lerp(star_class.temperature_k, t)),
        luminosity_mlsun=max(1, round(luminosity * 1000)),
        radius_milli_rsun=max(1, round(_lerp(star_class.radius_rsun, t) * 1000)),
        colour=star_class.colour,
    )


def _slots(
    rng: random.Random, star_index: int, star: StarProps, content: WorldgenContent
) -> tuple[PlanetSlot, ...]:
    planets = content.planets
    weights = content.stars.classes[star.star_class].planet_count_weights
    count = rng.choices(range(MAX_PLANETS + 1), weights=weights)[0]

    luminosity = star.luminosity_mlsun / 1000
    slots = []
    orbit = 0
    for index in range(1, count + 1):
        if index == 1:
            orbit_au = math.sqrt(luminosity) * rng.uniform(*planets.first_orbit_factor)
            orbit = max(1, round(orbit_au * 1000))
        else:
            orbit = max(orbit + 1, round(orbit * rng.uniform(*planets.orbit_ratio)))
        x, y = _point_on_ring(rng, orbit)
        slots.append(
            PlanetSlot(
                index=index,
                path=paths.planet_path(star_index, index),
                code=paths.planet_code(star_index, index),
                orbit_mau=orbit,
                x_mau=x,
                y_mau=y,
            )
        )
    return tuple(slots)


def _point_on_ring(rng: random.Random, radius: int) -> tuple[int, int]:
    """Uniform direction by rejection sampling (no trigonometry), scaled to `radius`."""
    while True:
        u = rng.uniform(-1.0, 1.0)
        v = rng.uniform(-1.0, 1.0)
        rho2 = u * u + v * v
        if 0.01 <= rho2 <= 1.0:
            norm = math.sqrt(rho2)
            return round(radius * u / norm), round(radius * v / norm)


def habitable_zone_mau(luminosity_mlsun: int) -> tuple[int, int]:
    luminosity = luminosity_mlsun / 1000
    return (
        round(1000 * math.sqrt(luminosity / 1.1)),
        round(1000 * math.sqrt(luminosity / 0.53)),
    )


def frost_line_mau(luminosity_mlsun: int) -> int:
    return round(1000 * 4.85 * math.sqrt(luminosity_mlsun / 1000))
