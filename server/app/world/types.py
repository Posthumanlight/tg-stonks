"""Generator outputs. Frozen and int-only (docs/world-gen.md, determinism rule 4)."""

from dataclasses import dataclass
from typing import Literal

LinkKind = Literal["lane", "bridge"]


@dataclass(frozen=True, slots=True)
class Cluster:
    index: int
    path: str
    code: str
    name: str
    x: int
    y: int
    radius: int
    stars: tuple[int, ...]  # star indices, ascending


@dataclass(frozen=True, slots=True)
class Star:
    index: int
    path: str
    code: str
    name: str
    x: int
    y: int
    cluster: int


@dataclass(frozen=True, slots=True)
class Link:
    a: int  # star index, a < b
    b: int
    length: int  # gu
    kind: LinkKind


@dataclass(frozen=True, slots=True)
class Galaxy:
    version: int
    clusters: tuple[Cluster, ...]
    stars: tuple[Star, ...]
    links: tuple[Link, ...]


@dataclass(frozen=True, slots=True)
class StarProps:
    star_class: str
    subclass: int  # 0 (hottest) .. 9
    temperature_k: int
    luminosity_mlsun: int  # milli solar luminosity
    radius_milli_rsun: int
    colour: str


@dataclass(frozen=True, slots=True)
class PlanetSlot:
    index: int  # 1-based, orbit order
    path: str
    code: str
    orbit_mau: int  # milli-AU
    x_mau: int  # static position in the system plane
    y_mau: int


@dataclass(frozen=True, slots=True)
class SystemSkeleton:
    """Output of the `system` generator: the star and its planet slots."""

    version: int
    star_index: int
    path: str
    star: StarProps
    slots: tuple[PlanetSlot, ...]


@dataclass(frozen=True, slots=True)
class Planet:
    """Output of the `planet` generator. The display name is resolved separately."""

    version: int
    index: int
    path: str
    code: str
    orbit_mau: int
    x_mau: int
    y_mau: int
    temperature_k: int
    temp_bucket: str
    size_class: str
    radius_km: int
    gravity_mg: int  # milli-g
    planet_type: str
    atmosphere: str
    landable: bool
    surface_n: int | None  # cube-sphere face resolution; None if not landable
    in_habitable_zone: bool
    resources: dict[str, int]  # category -> abundance 0..100, in content order
