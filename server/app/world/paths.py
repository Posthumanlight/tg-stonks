"""Object paths (stable IDs) and catalog codes. See docs/world-gen.md "Object paths"."""

import re
from dataclasses import dataclass

from app.world.errors import UnknownObject

GALAXY_PATH = "galaxy"

_STAR_RE = re.compile(r"^s/(0|[1-9]\d*)$")
_PLANET_RE = re.compile(r"^s/(0|[1-9]\d*)/p/([1-9]\d*)$")


def cluster_path(cluster: int) -> str:
    return f"c/{cluster}"


def star_path(star: int) -> str:
    return f"s/{star}"


def planet_path(star: int, planet: int) -> str:
    return f"s/{star}/p/{planet}"


def cluster_code(cluster: int) -> str:
    return f"C{cluster}"


def star_code(star: int) -> str:
    return f"S{star:03d}"


def planet_code(star: int, planet: int) -> str:
    return f"S{star:03d}-P{planet}"


@dataclass(frozen=True, slots=True)
class PlanetRef:
    star: int
    planet: int


def parse_star_path(path: str) -> int:
    if m := _STAR_RE.match(path):
        return int(m.group(1))
    raise UnknownObject(f"not a star path: {path!r}")


def parse_planet_path(path: str) -> PlanetRef:
    if m := _PLANET_RE.match(path):
        return PlanetRef(star=int(m.group(1)), planet=int(m.group(2)))
    raise UnknownObject(f"not a planet path: {path!r}")
