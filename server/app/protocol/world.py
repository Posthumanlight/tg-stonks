"""Static world data served over HTTP (docs/world-gen.md, "Delivery to the client")."""

from typing import Literal

from app.protocol.base import ProtocolModel


class ClusterView(ProtocolModel):
    index: int
    code: str
    name: str
    x: int
    y: int
    radius: int


class StarView(ProtocolModel):
    index: int
    code: str
    name: str
    x: int
    y: int
    cluster: int
    star_class: str
    subclass: int
    colour: str


class LinkView(ProtocolModel):
    a: int
    b: int
    kind: Literal["lane", "bridge"]
    length: int


class GalaxyView(ProtocolModel):
    """`GET /api/world/galaxy`: everything the star chart needs. Static per world."""

    version: int
    semi_axis_a: int
    semi_axis_b: int
    clusters: list[ClusterView]
    stars: list[StarView]
    links: list[LinkView]
