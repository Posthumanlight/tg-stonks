"""Galaxy v1 invariants (docs/world-gen.md "Galaxy invariants") and determinism.

The generator validates itself; these tests re-check the invariants independently so a
bug in `validate` can't hide a bad galaxy.
"""

from collections import deque

import pytest

from app.content.worldgen import WorldgenContent
from app.world import geometry as geo
from app.world.galaxy import v1
from app.world.types import Galaxy

SEEDS = range(25)


@pytest.fixture(scope="module")
def galaxies(content: WorldgenContent) -> dict[int, Galaxy]:
    return {seed: v1.generate(seed, content) for seed in SEEDS}


def _connected(nodes: list[int], edges: list[tuple[int, int]]) -> bool:
    if not nodes:
        return True
    adjacency: dict[int, list[int]] = {n: [] for n in nodes}
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    seen = {nodes[0]}
    queue = deque([nodes[0]])
    while queue:
        for nxt in adjacency[queue.popleft()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return len(seen) == len(nodes)


@pytest.mark.parametrize("seed", SEEDS)
def test_galaxy_invariants(
    seed: int, galaxies: dict[int, Galaxy], content: WorldgenContent
) -> None:
    g = galaxies[seed]
    p = content.galaxy
    lp = p.links

    assert len(g.stars) == p.star_count
    assert p.cluster_count[0] <= len(g.clusters) <= p.cluster_count[1]
    assert [s.index for s in g.stars] == list(range(p.star_count))
    assert sorted(s for c in g.clusters for s in c.stars) == list(range(p.star_count))
    assert len({s.name for s in g.stars}) == p.star_count
    assert len({c.name for c in g.clusters}) == len(g.clusters)

    for c in g.clusters:
        assert len(c.stars) >= p.min_stars_per_cluster
        assert all(g.stars[s].cluster == c.index for s in c.stars)
    for s in g.stars:
        assert geo.in_ellipse(s.x, s.y, p.semi_axis_a, p.semi_axis_b)
    for i, a in enumerate(g.stars):
        for b in g.stars[i + 1 :]:
            assert geo.dist2((a.x, a.y), (b.x, b.y)) >= p.min_star_separation**2
    for i, a in enumerate(g.clusters):
        for b in g.clusters[i + 1 :]:
            assert (
                geo.dist2((a.x, a.y), (b.x, b.y))
                >= (a.radius + b.radius + p.void_gap) ** 2
            )

    degree = [0] * len(g.stars)
    for link in g.links:
        degree[link.a] += 1
        degree[link.b] += 1
        same_cluster = g.stars[link.a].cluster == g.stars[link.b].cluster
        assert same_cluster == (link.kind == "lane")
    assert all(1 <= d <= lp.max_degree for d in degree)

    assert _connected(list(range(len(g.stars))), [(l.a, l.b) for l in g.links])
    for c in g.clusters:
        lanes = [
            (l.a, l.b)
            for l in g.links
            if l.kind == "lane" and g.stars[l.a].cluster == c.index
        ]
        assert _connected(list(c.stars), lanes)

    bridge_pairs = [
        tuple(sorted((g.stars[l.a].cluster, g.stars[l.b].cluster)))
        for l in g.links
        if l.kind == "bridge"
    ]
    assert len(bridge_pairs) == len(set(bridge_pairs))
    for c in g.clusters:
        assert (
            sum(c.index in pair for pair in bridge_pairs) <= lp.max_bridges_per_cluster
        )
    assert _connected([c.index for c in g.clusters], bridge_pairs)

    assert v1.find_crossing(g) is None


def test_galaxy_is_deterministic(
    content: WorldgenContent, galaxies: dict[int, Galaxy]
) -> None:
    assert v1.generate(3, content) == galaxies[3]
    assert galaxies[3] != galaxies[4]


def test_link_lengths_match_positions(galaxies: dict[int, Galaxy]) -> None:
    g = galaxies[0]
    for link in g.links:
        a, b = g.stars[link.a], g.stars[link.b]
        assert link.a < link.b
        assert (
            abs(link.length**2 - geo.dist2((a.x, a.y), (b.x, b.y)))
            <= 2 * link.length + 1
        )
