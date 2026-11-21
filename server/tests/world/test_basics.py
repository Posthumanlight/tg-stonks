"""Seeds, geometry, paths, naming."""

import random

import pytest

from app.world import geometry as geo
from app.world import naming, paths
from app.world.errors import UnknownObject
from app.world.seeds import derive_seed, make_rng


def test_derive_seed_is_stable_and_stream_separated() -> None:
    # A changed value here means every generated world changed: never "fix" this test.
    assert derive_seed(1, "galaxy", "links") == 12258423973184836355
    assert derive_seed(1, "galaxy", "links") != derive_seed(1, "galaxy", "names")
    assert derive_seed(1, "s/1", "star") != derive_seed(1, "s/2", "star")
    assert derive_seed(1, "s/1", "star") != derive_seed(2, "s/1", "star")


def test_make_rng_attempts_differ() -> None:
    first = make_rng(7, "galaxy", "x").random()
    assert make_rng(7, "galaxy", "x", attempt=0).random() == first
    assert make_rng(7, "galaxy", "x", attempt=1).random() != first


@pytest.mark.parametrize(
    ("a", "b", "c", "d", "expected"),
    [
        ((0, 0), (10, 10), (0, 10), (10, 0), True),  # X shape
        ((0, 0), (10, 0), (0, 5), (10, 5), False),  # parallel
        ((0, 0), (10, 0), (10, 0), (10, 10), False),  # shared endpoint only
        ((0, 0), (10, 0), (0, 0), (5, 0), True),  # shared endpoint, collinear overlap
        (
            (0, 0),
            (10, 0),
            (10, 0),
            (20, 0),
            False,
        ),  # shared endpoint, collinear, opposite
        ((0, 0), (10, 0), (5, 0), (5, 5), True),  # endpoint touches the middle
        (
            (0, 0),
            (10, 0),
            (2, 0),
            (8, 0),
            True,
        ),  # collinear overlap, no shared endpoint
        ((0, 0), (10, 0), (11, 0), (20, 0), False),  # collinear, disjoint
        ((0, 0), (10, 0), (0, 0), (10, 0), True),  # identical
    ],
)
def test_segments_cross(a, b, c, d, expected) -> None:
    assert geo.segments_cross(a, b, c, d) is expected
    assert geo.segments_cross(c, d, a, b) is expected


def test_in_ellipse_and_point_segment_distance() -> None:
    assert geo.in_ellipse(1000, 0, 1000, 600)
    assert not geo.in_ellipse(1001, 0, 1000, 600)
    assert geo.in_ellipse(0, -600, 1000, 600)
    assert geo.point_segment_dist2((5, 5), (0, 0), (10, 0)) == 25
    assert geo.point_segment_dist2((-3, 4), (0, 0), (10, 0)) == 25


def test_paths_and_codes() -> None:
    assert paths.planet_path(17, 2) == "s/17/p/2"
    assert paths.planet_code(7, 3) == "S007-P3"
    assert paths.parse_star_path("s/17") == 17
    assert paths.parse_planet_path("s/17/p/2") == paths.PlanetRef(17, 2)
    for bad in ("s/017", "s/1/p/0", "s/x", "galaxy", "s/1/p/2/r/0"):
        with pytest.raises(UnknownObject):
            paths.parse_planet_path(bad)


def test_naming() -> None:
    assert [naming.roman(n) for n in (1, 4, 8, 9, 14)] == [
        "I",
        "IV",
        "VIII",
        "IX",
        "XIV",
    ]
    assert naming.planet_display_name("Avior", 3, None) == "Avior III"
    assert naming.planet_display_name("Avior", 3, "New Hope") == "New Hope"
    pool = ["b", "a", "c", "d"]
    picked = naming.assign_names(pool, 3, random.Random(1))
    assert len(set(picked)) == 3
    # The pool's file order must not matter.
    assert naming.assign_names(list(reversed(pool)), 3, random.Random(1)) == picked
    with pytest.raises(ValueError):
        naming.assign_names(pool, 5, random.Random(1))
