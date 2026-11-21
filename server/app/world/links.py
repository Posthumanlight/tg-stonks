"""Hyperlane construction. See docs/world-gen.md "Link generation"."""

import math
import random
from collections.abc import Callable, Sequence

from app.content.worldgen import LinkParams
from app.world import geometry as geo
from app.world.errors import GenerationFailed
from app.world.geometry import Point
from app.world.types import Link, LinkKind


def prim_mst(
    nodes: Sequence[int], weight: Callable[[int, int], int]
) -> list[tuple[int, int]]:
    """Minimum spanning tree over `nodes`; ties broken by (weight, from-node, node)."""
    if len(nodes) < 2:
        return []
    root = nodes[0]
    best = {v: (weight(root, v), root) for v in nodes[1:]}
    edges = []
    while best:
        v = min(best, key=lambda u: (best[u][0], best[u][1], u))
        _, frm = best.pop(v)
        edges.append((min(frm, v), max(frm, v)))
        for u in best:
            candidate = (weight(v, u), v)
            if candidate < best[u]:
                best[u] = candidate
    return edges


class _LinkBuilder:
    def __init__(
        self,
        points: Sequence[Point],
        members: Sequence[Sequence[int]],
        cluster_of: Sequence[int],
        cluster_centres: Sequence[Point],
        cluster_radii: Sequence[int],
        params: LinkParams,
        rng: random.Random,
    ) -> None:
        self.points = points
        self.members = members
        self.cluster_of = cluster_of
        self.centres = cluster_centres
        self.radii = cluster_radii
        self.params = params
        self.rng = rng
        self.edges: dict[tuple[int, int], LinkKind] = {}
        self.degree = [0] * len(points)
        self.bridges_per_cluster = [0] * len(members)

    # --- helpers ---------------------------------------------------------------------

    def d2(self, a: int, b: int) -> int:
        return geo.dist2(self.points[a], self.points[b])

    def has(self, a: int, b: int) -> bool:
        return (min(a, b), max(a, b)) in self.edges

    def crosses(self, a: int, b: int) -> bool:
        pa, pb = self.points[a], self.points[b]
        return any(
            geo.segments_cross(pa, pb, self.points[c], self.points[d])
            for c, d in self.edges
        )

    def degree_ok(self, a: int, b: int) -> bool:
        return (
            self.degree[a] < self.params.max_degree
            and self.degree[b] < self.params.max_degree
        )

    def add(self, a: int, b: int, kind: LinkKind) -> None:
        self.edges[(min(a, b), max(a, b))] = kind
        self.degree[a] += 1
        self.degree[b] += 1

    def bridge_clear(self, a: int, b: int, ci: int, cj: int) -> bool:
        """The bridge keeps clear of every third cluster (passes through void, not clusters)."""
        pa, pb = self.points[a], self.points[b]
        for c, centre in enumerate(self.centres):
            if c in (ci, cj):
                continue
            clearance = self.params.bridge_clearance * self.radii[c]
            if geo.point_segment_dist2(centre, pa, pb) < clearance * clearance:
                return False
        return True

    # --- construction steps ----------------------------------------------------------

    def intra_cluster_msts(self) -> None:
        for stars in self.members:
            for a, b in prim_mst(stars, self.d2):
                self.add(a, b, "lane")

    def cluster_pair_weights(self) -> dict[tuple[int, int], int]:
        k = len(self.members)
        return {
            (i, j): min(self.d2(a, b) for a in self.members[i] for b in self.members[j])
            for i in range(k)
            for j in range(i + 1, k)
        }

    def try_bridge(self, ci: int, cj: int, required: bool) -> bool:
        candidates = sorted(
            (self.d2(a, b), min(a, b), max(a, b))
            for a in self.members[ci]
            for b in self.members[cj]
        )

        def ok(a: int, b: int) -> bool:
            return (
                self.degree_ok(a, b)
                and self.bridge_clear(a, b, ci, cj)
                and not self.crosses(a, b)
            )

        top = [
            (a, b)
            for _, a, b in candidates[: self.params.bridge_candidates]
            if ok(a, b)
        ]
        if top:
            a, b = self.rng.choice(top)
        elif required:
            fallback = next(
                (
                    (a, b)
                    for _, a, b in candidates[self.params.bridge_candidates :]
                    if ok(a, b)
                ),
                None,
            )
            if fallback is None:
                return False
            a, b = fallback
        else:
            return False
        self.add(a, b, "bridge")
        self.bridges_per_cluster[ci] += 1
        self.bridges_per_cluster[cj] += 1
        return True

    def bridges(self) -> None:
        weights = self.cluster_pair_weights()
        k = len(self.members)
        spanning = prim_mst(
            list(range(k)), lambda i, j: weights[(min(i, j), max(i, j))]
        )
        for ci, cj in sorted(spanning, key=lambda pair: (weights[pair], pair)):
            if not self.try_bridge(ci, cj, required=True):
                raise GenerationFailed(
                    f"no valid bridge between clusters {ci} and {cj}"
                )

        spanning_set = set(spanning)
        others = sorted(
            (pair for pair in weights if pair not in spanning_set),
            key=lambda pair: (weights[pair], pair),
        )
        extra = round(k * self.params.extra_bridge_ratio)
        limit = self.params.max_bridges_per_cluster
        for _ in range(min(extra, len(others))):
            rank = self.rng.choices(
                range(len(others)), weights=[1 / (r + 1) for r in range(len(others))]
            )[0]
            ci, cj = others.pop(rank)
            if (
                self.bridges_per_cluster[ci] >= limit
                or self.bridges_per_cluster[cj] >= limit
            ):
                continue
            self.try_bridge(ci, cj, required=False)

    def extra_lanes(self) -> None:
        p = self.params
        for s in range(len(self.points)):
            cluster = self.cluster_of[s]
            neighbours = sorted(
                (t for t in self.members[cluster] if t != s),
                key=lambda t: (self.d2(s, t), t),
            )[: p.k_nearest]
            max_len2 = (p.max_lane_length * self.radii[cluster]) ** 2
            for t in neighbours:
                roll = (
                    self.rng.random()
                )  # always drawn, so RNG use doesn't depend on state
                if roll >= p.p_extra or self.has(s, t) or not self.degree_ok(s, t):
                    continue
                if self.d2(s, t) > max_len2 or self.crosses(s, t):
                    continue
                self.add(s, t, "lane")

    def links(self) -> list[Link]:
        return [
            Link(a=a, b=b, length=round(math.sqrt(self.d2(a, b))), kind=kind)
            for (a, b), kind in sorted(self.edges.items())
        ]


def build_links(
    points: Sequence[Point],
    members: Sequence[Sequence[int]],
    cluster_of: Sequence[int],
    cluster_centres: Sequence[Point],
    cluster_radii: Sequence[int],
    params: LinkParams,
    rng: random.Random,
) -> list[Link]:
    """Lanes inside clusters (MST + extras) and bridges between clusters, never crossing."""
    builder = _LinkBuilder(
        points, members, cluster_of, cluster_centres, cluster_radii, params, rng
    )
    builder.intra_cluster_msts()
    builder.bridges()
    builder.extra_lanes()
    return builder.links()
