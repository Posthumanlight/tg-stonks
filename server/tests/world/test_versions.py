"""Pinning rules and the version registry."""

import pytest

from app.world import versions
from app.world.errors import UnknownObject


def test_planet_delta_pins_planet_and_its_system_skeleton() -> None:
    assert versions.pins_for_delta(versions.PLANET, "s/17/p/2") == [
        ("s/17/p/2", "planet"),
        ("s/17", "system"),
    ]


def test_star_delta_pins_only_the_system() -> None:
    assert versions.pins_for_delta(versions.SYSTEM, "s/17") == [("s/17", "system")]


def test_galaxy_is_not_pinned_per_object() -> None:
    with pytest.raises(ValueError):
        versions.pins_for_delta(versions.GALAXY, "galaxy")


def test_planet_generator_needs_a_planet_path() -> None:
    with pytest.raises(UnknownObject):
        versions.pins_for_delta(versions.PLANET, "s/17")


def test_registry() -> None:
    assert versions.LATEST == {"galaxy": 1, "system": 1, "planet": 1}
    assert versions.missing_versions([("planet", 1), ("system", 1)]) == []
    assert versions.missing_versions([("planet", 7), ("nope", 1), ("planet", 7)]) == [
        ("nope", 1),
        ("planet", 7),
    ]
