"""Planet generator v1: physical properties, type and resources of one planet slot.

See docs/world-gen.md "Planet physical properties". Root object: `s/<star>/p/<planet>`.
Input is the system skeleton (structural context): the star and this planet's slot.
"""

import math

from app.content.worldgen import WorldgenContent
from app.world.errors import UnknownObject
from app.world.seeds import make_rng
from app.world.system.v1 import frost_line_mau, habitable_zone_mau
from app.world.types import Planet, SystemSkeleton

VERSION = 1
EARTH_RADIUS_KM = 6371


def generate(
    world_seed: int,
    skeleton: SystemSkeleton,
    planet_index: int,
    content: WorldgenContent,
) -> Planet:
    if not 1 <= planet_index <= len(skeleton.slots):
        raise UnknownObject(f"{skeleton.path} has no planet {planet_index}")
    slot = skeleton.slots[planet_index - 1]
    star = skeleton.star
    planets = content.planets
    rng = make_rng(world_seed, slot.path, "planet")

    # Equilibrium temperature with a fixed classification albedo; only sqrt, no pow.
    luminosity = star.luminosity_mlsun / 1000
    distance_au = slot.orbit_mau / 1000
    albedo_factor = math.sqrt(math.sqrt(1 - planets.classification_albedo))
    temperature = round(
        278 * albedo_factor * math.sqrt(math.sqrt(luminosity)) / math.sqrt(distance_au)
    )
    bucket = next(b.id for b in planets.temperature_buckets if temperature >= b.min_k)

    beyond_frost_line = slot.orbit_mau >= frost_line_mau(star.luminosity_mlsun)
    sizes = list(planets.size_classes.items())
    size_id, size = rng.choices(
        sizes,
        weights=[
            s.weight_outer if beyond_frost_line else s.weight_inner for _, s in sizes
        ],
    )[0]
    radius_km = rng.randint(*size.radius_km)

    candidates = [
        (tid, t) for tid, t in planets.types.items() if t.allows(temperature, size_id)
    ]
    type_id, planet_type = rng.choices(
        candidates, weights=[t.weight_for(size_id) for _, t in candidates]
    )[0]

    hz_inner, hz_outer = habitable_zone_mau(star.luminosity_mlsun)

    # Resources: categories in content order; modifiers only touch present categories.
    res_rng = make_rng(world_seed, slot.path, "resources")
    modifiers = content.stars.classes[star.star_class].resource_modifiers
    resources: dict[str, int] = {}
    for category in content.resources.categories:
        bounds = planet_type.resources.get(category.id)
        if bounds is None:
            resources[category.id] = 0
            continue
        value = res_rng.randint(*bounds) + modifiers.get(category.id, 0)
        resources[category.id] = max(0, min(100, value))

    return Planet(
        version=VERSION,
        index=slot.index,
        path=slot.path,
        code=slot.code,
        orbit_mau=slot.orbit_mau,
        x_mau=slot.x_mau,
        y_mau=slot.y_mau,
        temperature_k=temperature,
        temp_bucket=bucket,
        size_class=size_id,
        radius_km=radius_km,
        gravity_mg=round(
            1000 * radius_km / EARTH_RADIUS_KM * planet_type.density_factor
        ),
        planet_type=type_id,
        atmosphere=planet_type.atmosphere,
        landable=planet_type.landable,
        surface_n=size.surface_n if planet_type.landable else None,
        in_habitable_zone=hz_inner <= slot.orbit_mau <= hz_outer,
        resources=resources,
    )
