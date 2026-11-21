"""Schemas and loader for `content/worldgen/*.toml` (see docs/world-gen.md).

Validated once at startup; invalid content raises `pydantic.ValidationError`.
"""

import tomllib
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.config import REPO_ROOT

DEFAULT_CONTENT_DIR = REPO_ROOT / "content" / "worldgen"


def _ordered(value: tuple[float, float]) -> tuple[float, float]:
    if value[0] > value[1]:
        raise ValueError(f"range lower bound {value[0]} exceeds upper bound {value[1]}")
    return value


IntRange = Annotated[tuple[int, int], AfterValidator(_ordered)]
FloatRange = Annotated[tuple[float, float], AfterValidator(_ordered)]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- galaxy.toml ---------------------------------------------------------------------


class LinkParams(_Model):
    k_nearest: int = Field(ge=1)
    p_extra: float = Field(ge=0, le=1)
    max_degree: int = Field(ge=2)
    max_lane_length: float = Field(gt=0)
    extra_bridge_ratio: float = Field(ge=0)
    bridge_candidates: int = Field(ge=1)
    max_bridges_per_cluster: int = Field(ge=1)
    bridge_clearance: float = Field(ge=0)


class GalaxyParams(_Model):
    star_count: int = Field(ge=1)
    semi_axis_a: int = Field(gt=0)
    semi_axis_b: int = Field(gt=0)
    edge_margin: float = Field(gt=0, le=1)
    cluster_count: IntRange
    min_stars_per_cluster: int = Field(ge=1)
    cluster_size_weights: tuple[Annotated[int, Field(gt=0)], ...] = Field(min_length=1)
    radius_per_sqrt_star: float = Field(gt=0)
    radius_jitter: FloatRange
    void_gap: int = Field(ge=0)
    centre_bias: float = Field(ge=0, le=1)
    min_star_separation: int = Field(ge=1)
    max_placement_attempts: int = Field(ge=1)
    max_generation_attempts: int = Field(ge=1)
    links: LinkParams

    @model_validator(mode="after")
    def _enough_stars(self) -> "GalaxyParams":
        if self.cluster_count[0] < 1:
            raise ValueError("cluster_count must be >= 1")
        if self.star_count < self.cluster_count[1] * self.min_stars_per_cluster:
            raise ValueError(
                "star_count must be >= max(cluster_count) x min_stars_per_cluster"
            )
        return self


# --- stars.toml ----------------------------------------------------------------------


class StarClass(_Model):
    weight: int = Field(gt=0)
    temperature_k: IntRange
    luminosity_lsun: FloatRange
    radius_rsun: FloatRange
    colour: str
    planet_count_weights: tuple[Annotated[int, Field(ge=0)], ...] = Field(
        min_length=9, max_length=9
    )
    resource_modifiers: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "StarClass":
        if self.luminosity_lsun[0] <= 0 or self.radius_rsun[0] <= 0:
            raise ValueError("luminosity and radius must be positive")
        if sum(self.planet_count_weights) == 0:
            raise ValueError("planet_count_weights must not all be zero")
        return self


class StarsContent(_Model):
    classes: dict[str, StarClass] = Field(min_length=1)


# --- planets.toml --------------------------------------------------------------------


class TemperatureBucket(_Model):
    id: str
    min_k: int = Field(ge=0)


class SizeClass(_Model):
    radius_km: IntRange
    weight_inner: int = Field(ge=0)
    weight_outer: int = Field(ge=0)
    surface_n: int | None = Field(default=None, ge=1)


class PlanetType(_Model):
    min_k: int | None = Field(default=None, ge=0)
    max_k: int | None = Field(default=None, ge=0)
    sizes: tuple[str, ...] = Field(min_length=1)
    weight: int = Field(gt=0)
    size_weights: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    atmosphere: str
    landable: bool
    density_factor: float = Field(gt=0)
    name_key: str
    sprite: str
    resources: dict[str, IntRange] = Field(default_factory=dict)

    def weight_for(self, size: str) -> int:
        return self.size_weights.get(size, self.weight)

    def allows(self, temperature_k: int, size: str) -> bool:
        """True if this type can be picked for the given temperature and size."""
        if size not in self.sizes or self.weight_for(size) == 0:
            return False
        if self.min_k is not None and temperature_k < self.min_k:
            return False
        if self.max_k is not None and temperature_k >= self.max_k:
            return False
        return True

    @model_validator(mode="after")
    def _check(self) -> "PlanetType":
        if (
            self.min_k is not None
            and self.max_k is not None
            and self.min_k >= self.max_k
        ):
            raise ValueError("min_k must be < max_k")
        if unknown := set(self.size_weights) - set(self.sizes):
            raise ValueError(
                f"size_weights for sizes not in `sizes`: {sorted(unknown)}"
            )
        for category, (low, high) in self.resources.items():
            if low < 0 or high > 100:
                raise ValueError(f"resource {category!r} range must be within 0..100")
        return self


class PlanetsContent(_Model):
    first_orbit_factor: FloatRange
    orbit_ratio: FloatRange
    classification_albedo: float = Field(ge=0, lt=1)
    temperature_buckets: tuple[TemperatureBucket, ...] = Field(min_length=1)
    size_classes: dict[str, SizeClass] = Field(min_length=1)
    types: dict[str, PlanetType] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "PlanetsContent":
        if self.first_orbit_factor[0] <= 0:
            raise ValueError("first_orbit_factor must be positive")
        if self.orbit_ratio[0] <= 1:
            raise ValueError("orbit_ratio must be > 1 so orbits strictly increase")

        mins = [b.min_k for b in self.temperature_buckets]
        if mins != sorted(mins, reverse=True) or len(set(mins)) != len(mins):
            raise ValueError(
                "temperature_buckets must be ordered by strictly decreasing min_k"
            )
        if mins[-1] != 0:
            raise ValueError("the last temperature bucket must have min_k = 0")

        if sum(s.weight_inner for s in self.size_classes.values()) == 0:
            raise ValueError("size class weight_inner must not all be zero")
        if sum(s.weight_outer for s in self.size_classes.values()) == 0:
            raise ValueError("size class weight_outer must not all be zero")

        for type_id, planet_type in self.types.items():
            for size in planet_type.sizes:
                if size not in self.size_classes:
                    raise ValueError(f"type {type_id!r}: unknown size class {size!r}")
                if planet_type.landable and self.size_classes[size].surface_n is None:
                    raise ValueError(
                        f"type {type_id!r} is landable but size {size!r} has no surface_n"
                    )

        for size in self.size_classes:
            self._check_coverage(size)
        return self

    def _check_coverage(self, size: str) -> None:
        """Types allowing `size` must jointly cover every temperature in [0, inf)."""
        intervals = sorted(
            (
                (t.min_k or 0, t.max_k)
                for t in self.types.values()
                if size in t.sizes and t.weight_for(size) > 0
            ),
            key=lambda interval: interval[0],
        )
        covered_to = 0
        for low, high in intervals:
            if low > covered_to:
                break
            if high is None:
                return
            covered_to = max(covered_to, high)
        raise ValueError(
            f"planet types for size {size!r} leave temperatures >= {covered_to} K uncovered"
        )


# --- resources.toml / names.toml -----------------------------------------------------


class ResourceCategory(_Model):
    id: str
    name_key: str


class ResourcesContent(_Model):
    categories: tuple[ResourceCategory, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> "ResourcesContent":
        ids = [c.id for c in self.categories]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate resource category ids")
        return self


def _unique_names(names: tuple[str, ...]) -> tuple[str, ...]:
    if any(not n.strip() for n in names):
        raise ValueError("names must not be blank")
    if len(set(names)) != len(names):
        duplicates = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"duplicate names: {duplicates}")
    return names


class NamesContent(_Model):
    star_names: Annotated[tuple[str, ...], AfterValidator(_unique_names)]
    cluster_names: Annotated[tuple[str, ...], AfterValidator(_unique_names)]


# --- all together --------------------------------------------------------------------


class WorldgenContent(_Model):
    galaxy: GalaxyParams
    stars: StarsContent
    planets: PlanetsContent
    resources: ResourcesContent
    names: NamesContent

    @model_validator(mode="after")
    def _cross_checks(self) -> "WorldgenContent":
        if len(self.names.star_names) < self.galaxy.star_count:
            raise ValueError(
                f"names.star_names has {len(self.names.star_names)} names, "
                f"need >= star_count ({self.galaxy.star_count})"
            )
        if len(self.names.cluster_names) < self.galaxy.cluster_count[1]:
            raise ValueError(
                "names.cluster_names has fewer names than max cluster_count"
            )

        categories = {c.id for c in self.resources.categories}
        for type_id, planet_type in self.planets.types.items():
            if unknown := set(planet_type.resources) - categories:
                raise ValueError(
                    f"type {type_id!r}: unknown resources {sorted(unknown)}"
                )
        for class_id, star_class in self.stars.classes.items():
            if unknown := set(star_class.resource_modifiers) - categories:
                raise ValueError(
                    f"star class {class_id!r}: unknown resources {sorted(unknown)}"
                )
        return self


CONTENT_FILES = ("galaxy", "stars", "planets", "resources", "names")


def load_worldgen_content(directory: Path = DEFAULT_CONTENT_DIR) -> WorldgenContent:
    """Read and validate all world-gen TOML files from `directory`."""
    data = {}
    for name in CONTENT_FILES:
        with open(directory / f"{name}.toml", "rb") as f:
            data[name] = tomllib.load(f)
    return WorldgenContent.model_validate(data)
