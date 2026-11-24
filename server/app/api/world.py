"""Static world data for the client. Generated once per process, served with an ETag."""

from dataclasses import dataclass

from fastapi import APIRouter, Request, Response

from app.persistence.worldgen_repo import Pins
from app.protocol.world import ClusterView, GalaxyView, LinkView, StarView
from app.world import versions
from app.world.canonical import output_hash
from app.world.generator import WorldGenerator

router = APIRouter(prefix="/world")


@dataclass(frozen=True, slots=True)
class CachedGalaxy:
    body: bytes  # serialized GalaxyView
    etag: str  # quoted strong ETag


def build_galaxy_view(generator: WorldGenerator, pins: Pins) -> GalaxyView:
    """Assemble the star-chart payload. Pure; star class honours `system` pins."""
    galaxy = generator.galaxy
    params = generator.content.galaxy
    stars = []
    for star in galaxy.stars:
        props = generator.system(
            star.index, pins.get((star.path, versions.SYSTEM))
        ).star
        stars.append(
            StarView(
                index=star.index,
                code=star.code,
                name=star.name,
                x=star.x,
                y=star.y,
                cluster=star.cluster,
                star_class=props.star_class,
                subclass=props.subclass,
                colour=props.colour,
            )
        )
    return GalaxyView(
        version=galaxy.version,
        semi_axis_a=params.semi_axis_a,
        semi_axis_b=params.semi_axis_b,
        clusters=[
            ClusterView(
                index=c.index, code=c.code, name=c.name, x=c.x, y=c.y, radius=c.radius
            )
            for c in galaxy.clusters
        ],
        stars=stars,
        links=[
            LinkView(a=link.a, b=link.b, kind=link.kind, length=link.length)
            for link in galaxy.links
        ],
    )


def cache_galaxy(view: GalaxyView) -> CachedGalaxy:
    return CachedGalaxy(
        body=view.model_dump_json().encode(),
        etag=f'"{output_hash(view.model_dump(mode="json"))}"',
    )


@router.get("/galaxy", response_model=GalaxyView)
async def get_galaxy(request: Request) -> Response:
    cached: CachedGalaxy = request.app.state.galaxy
    headers = {"ETag": cached.etag, "Cache-Control": "no-cache"}
    if cached.etag in _etags(request.headers.get("if-none-match")):
        return Response(status_code=304, headers=headers)
    return Response(cached.body, media_type="application/json", headers=headers)


def _etags(header: str | None) -> set[str]:
    if not header:
        return set()
    return {tag.strip().removeprefix("W/") for tag in header.split(",")}
