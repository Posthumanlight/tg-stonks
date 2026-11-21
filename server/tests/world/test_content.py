"""Startup validation of content/worldgen/*.toml."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.content.worldgen import WorldgenContent


def test_repo_content_is_valid(content: WorldgenContent) -> None:
    assert len(content.names.star_names) >= content.galaxy.star_count
    assert content.planets.temperature_buckets[-1].min_k == 0


def _expect_invalid(raw: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        WorldgenContent.model_validate(raw)


def test_rejects_too_few_star_names(raw_content: dict[str, Any]) -> None:
    raw_content["names"]["star_names"] = raw_content["names"]["star_names"][:50]
    _expect_invalid(raw_content, "star_count")


def test_rejects_duplicate_names(raw_content: dict[str, Any]) -> None:
    raw_content["names"]["cluster_names"].append(
        raw_content["names"]["cluster_names"][0]
    )
    _expect_invalid(raw_content, "duplicate names")


def test_rejects_temperature_gap(raw_content: dict[str, Any]) -> None:
    # Barren is the catch-all: without it, tiny planets have no type between
    # 250 K (ice) and 600 K (lava).
    del raw_content["planets"]["types"]["barren"]
    _expect_invalid(raw_content, "uncovered")


def test_rejects_unknown_resource(raw_content: dict[str, Any]) -> None:
    raw_content["planets"]["types"]["lava"]["resources"]["unobtainium"] = [1, 2]
    _expect_invalid(raw_content, "unknown resources")


def test_rejects_unknown_size(raw_content: dict[str, Any]) -> None:
    raw_content["planets"]["types"]["lava"]["sizes"].append("huge")
    _expect_invalid(raw_content, "unknown size class")


def test_rejects_landable_type_without_surface(raw_content: dict[str, Any]) -> None:
    raw_content["planets"]["types"]["gas_giant"]["landable"] = True
    _expect_invalid(raw_content, "no surface_n")


def test_rejects_inverted_range(raw_content: dict[str, Any]) -> None:
    raw_content["galaxy"]["radius_jitter"] = [1.2, 0.8]
    _expect_invalid(raw_content, "exceeds upper bound")


def test_rejects_unknown_keys(raw_content: dict[str, Any]) -> None:
    raw_content["galaxy"]["star_cuont"] = 5
    _expect_invalid(raw_content, "star_cuont")
