"""Galaxy generator v1: clusters, stars, names, links. See docs/world-gen.md "Galaxy generation"."""

import math
from collections import deque

from app.content.worldgen import GalaxyParams, WorldgenContent
from app.world import geometry as geo
from app.world import naming, paths
from app.world.errors import GenerationFailed
from app.world.links import build_links
from app.world.seeds import make_rng
from app.world.types import Cluster, Galaxy, Link, Star

VERSION = 1
PATH = paths.GALAXY_PATH


def generate(world_seed: int, content: WorldgenContent) -> Galaxy:
    params = content.galaxy
    last_error: GenerationFailed | None = None
    for attempt in range(params.max_generation_attempts):
        try:
            galaxy = _generate_attempt(world_seed, content, attempt)
            validate(galaxy, params)
            return galaxy
        except GenerationFailed as exc:
            last_error = exc
    raise GenerationFailed(
        f"galaxy: all {params.max_generation_attempts} attempts failed; last: {last_error}"
    )


def _generate_attempt(
    world_seed: int, content: WorldgenContent, attempt: int
) -> Galaxy:
    p = content.galaxy

    # Step 1: cluster sizes and radii.
    rng = make_rng(world_seed, PATH, "cluster_sizes", attempt)
    k = rng.randint(*p.cluster_count)
    size_weights = [rng.choice(p.cluster_size_weights) for _ in range(k)]
    counts = [p.min_stars_per_cluster] * k
    for _ in range(p.star_count - k * p.min_stars_per_cluster):
        counts[rng.choices(range(k), weights=size_weights)[0]] += 1
    radii = [
        round(p.radius_per_sqrt_star * math.sqrt(n) * rng.uniform(*p.radius_jitter))
        for n in counts
    ]

    # Step 2: cluster centres, largest first.
    rng = make_rng(world_seed, PATH, "cluster_centres", attempt)
    inner_a = p.semi_axis_a * p.edge_margin
    inner_b = p.semi_axis_b * p.edge_margin
    centres: dict[int, geo.Point] = {}
    for i in sorted(range(k), key=lambda i: (-radii[i], i)):
        for _ in range(p.max_placement_attempts):
            x = round(rng.uniform(-inner_a, inner_a))
            y = round(rng.uniform(-inner_b, inner_b))
            if not geo.in_ellipse(x, y, inner_a, inner_b):
                continue
            if all(
                geo.dist2((x, y), centres[j]) >= (radii[i] + radii[j] + p.void_gap) ** 2
                for j in centres
            ):
                centres[i] = (x, y)
                break
        else:
            raise GenerationFailed(f"could not place cluster centre {i}")

    # Step 3: star positions.
    rng = make_rng(world_seed, PATH, "star_positions", attempt)
    sep2 = p.min_star_separation**2
    placed: list[tuple[int, int, int]] = []  # (x, y, generation cluster index)
    for i in range(k):
        cx, cy = centres[i]
        for _ in range(counts[i]):
            for _ in range(p.max_placement_attempts):
                u = rng.uniform(-1.0, 1.0)
                v = rng.uniform(-1.0, 1.0)
                rho2 = u * u + v * v
                if rho2 > 1.0 or rng.random() >= 1.0 - p.centre_bias * rho2:
                    continue
                x = cx + round(radii[i] * u)
                y = cy + round(radii[i] * v)
                if not geo.in_ellipse(x, y, p.semi_axis_a, p.semi_axis_b):
                    continue
                if any(geo.dist2((x, y), (sx, sy)) < sep2 for sx, sy, _ in placed):
                    continue
                placed.append((x, y, i))
                break
            else:
                raise GenerationFailed(f"could not place a star in cluster {i}")

    # Step 4: stable ordering -> indices.
    cluster_order = sorted(range(k), key=lambda i: (centres[i], i))
    final_index = {gen: idx for idx, gen in enumerate(cluster_order)}
    ordered = sorted((final_index[i], x, y) for x, y, i in placed)

    points = [(x, y) for _, x, y in ordered]
    cluster_of = [c for c, _, _ in ordered]
    members = [[s for s, c in enumerate(cluster_of) if c == ci] for ci in range(k)]
    final_centres = [centres[gen] for gen in cluster_order]
    final_radii = [radii[gen] for gen in cluster_order]

    star_names = naming.assign_names(
        content.names.star_names, len(points), make_rng(world_seed, PATH, "names")
    )
    cluster_names = naming.assign_names(
        content.names.cluster_names, k, make_rng(world_seed, PATH, "cluster_names")
    )

    links = build_links(
        points,
        members,
        cluster_of,
        final_centres,
        final_radii,
        p.links,
        make_rng(world_seed, PATH, "links", attempt),
    )

    clusters = tuple(
        Cluster(
            index=ci,
            path=paths.cluster_path(ci),
            code=paths.cluster_code(ci),
            name=cluster_names[ci],
            x=final_centres[ci][0],
            y=final_centres[ci][1],
            radius=final_radii[ci],
            stars=tuple(members[ci]),
        )
        for ci in range(k)
    )
    stars = tuple(
        Star(
            index=s,
            path=paths.star_path(s),
            code=paths.star_code(s),
            name=star_names[s],
            x=x,
            y=y,
            cluster=cluster_of[s],
        )
        for s, (x, y) in enumerate(points)
    )
    return Galaxy(version=VERSION, clusters=clusters, stars=stars, links=tuple(links))


def validate(galaxy: Galaxy, params: GalaxyParams) -> None:
    """Raise GenerationFailed if any galaxy invariant (docs/world-gen.md) is violated."""
    stars, clusters, links = galaxy.stars, galaxy.clusters, galaxy.links
    lp = params.links

    def fail(reason: str) -> None:
        raise GenerationFailed(reason)

    if len(stars) != params.star_count:
        fail(f"expected {params.star_count} stars, got {len(stars)}")
    for s in stars:
        if not geo.in_ellipse(s.x, s.y, params.semi_axis_a, params.semi_axis_b):
            fail(f"star {s.index} outside the galaxy ellipse")
    sep2 = params.min_star_separation**2
    for i, a in enumerate(stars):
        for b in stars[i + 1 :]:
            if geo.dist2((a.x, a.y), (b.x, b.y)) < sep2:
                fail(f"stars {a.index} and {b.index} too close")
    for i, a in enumerate(clusters):
        for b in clusters[i + 1 :]:
            if (
                geo.dist2((a.x, a.y), (b.x, b.y))
                < (a.radius + b.radius + params.void_gap) ** 2
            ):
                fail(f"clusters {a.index} and {b.index} closer than void_gap")

    adjacency: list[list[int]] = [[] for _ in stars]
    lane_adjacency: list[list[int]] = [[] for _ in stars]
    bridge_pairs: set[tuple[int, int]] = set()
    bridges_per_cluster = [0] * len(clusters)
    for link in links:
        if not link.a < link.b:
            fail(f"link {link} not normalised (a < b)")
        adjacency[link.a].append(link.b)
        adjacency[link.b].append(link.a)
        ca, cb = stars[link.a].cluster, stars[link.b].cluster
        if link.kind == "lane":
            if ca != cb:
                fail(f"lane {link.a}-{link.b} joins different clusters")
            lane_adjacency[link.a].append(link.b)
            lane_adjacency[link.b].append(link.a)
        else:
            if ca == cb:
                fail(f"bridge {link.a}-{link.b} inside one cluster")
            pair = (min(ca, cb), max(ca, cb))
            if pair in bridge_pairs:
                fail(f"more than one bridge between clusters {pair}")
            bridge_pairs.add(pair)
            bridges_per_cluster[ca] += 1
            bridges_per_cluster[cb] += 1

    for s, neighbours in enumerate(adjacency):
        if not 1 <= len(neighbours) <= lp.max_degree:
            fail(f"star {s} has degree {len(neighbours)}")
    if len(_reachable(0, adjacency)) != len(stars):
        fail("link graph is not connected")
    for cluster in clusters:
        reached = _reachable(cluster.stars[0], lane_adjacency)
        if reached != set(cluster.stars):
            fail(f"lanes of cluster {cluster.index} do not connect it")
    for ci, count in enumerate(bridges_per_cluster):
        if count > lp.max_bridges_per_cluster:
            fail(f"cluster {ci} has {count} bridges")
    cluster_adjacency: list[list[int]] = [[] for _ in clusters]
    for ca, cb in bridge_pairs:
        cluster_adjacency[ca].append(cb)
        cluster_adjacency[cb].append(ca)
    if len(_reachable(0, cluster_adjacency)) != len(clusters):
        fail("bridges do not connect all clusters")

    if crossing := find_crossing(galaxy):
        fail(f"links {crossing[0]} and {crossing[1]} cross")


def find_crossing(galaxy: Galaxy) -> tuple[Link, Link] | None:
    stars = galaxy.stars
    links = galaxy.links
    for i, l1 in enumerate(links):
        p1, p2 = (stars[l1.a].x, stars[l1.a].y), (stars[l1.b].x, stars[l1.b].y)
        for l2 in links[i + 1 :]:
            q1, q2 = (stars[l2.a].x, stars[l2.a].y), (stars[l2.b].x, stars[l2.b].y)
            if geo.segments_cross(p1, p2, q1, q2):
                return l1, l2
    return None


def _reachable(start: int, adjacency: list[list[int]]) -> set[int]:
    seen = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nxt in adjacency[node]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen
