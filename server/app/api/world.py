"""Static world data for the client. Generated once per process, served with an ETag."""

from fastapi import APIRouter, Depends, Request, Response

from app.api.static_json import StaticJson, respond
from app.auth.dependencies import current_user
from app.persistence.worldgen_repo import Pins
from app.protocol.world import ClusterView, GalaxyView, LinkView, StarView
from app.world import versions
from app.world.generator import WorldGenerator

# Game data is for signed-in players only (docs/architecture.md "Authorization").
router = APIRouter(prefix="/world", dependencies=[Depends(current_user)])


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


def cache_galaxy(view: GalaxyView) -> StaticJson:
    return StaticJson.of(view)


@router.get("/galaxy", response_model=GalaxyView)
async def get_galaxy(request: Request) -> Response:
    return respond(request, request.app.state.galaxy)
