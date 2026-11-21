import copy
import tomllib
from typing import Any

import pytest

from app.content.worldgen import (
    CONTENT_FILES,
    DEFAULT_CONTENT_DIR,
    WorldgenContent,
    load_worldgen_content,
)


@pytest.fixture(scope="session")
def content() -> WorldgenContent:
    return load_worldgen_content()


@pytest.fixture(scope="session")
def _raw_content() -> dict[str, Any]:
    data = {}
    for name in CONTENT_FILES:
        with open(DEFAULT_CONTENT_DIR / f"{name}.toml", "rb") as f:
            data[name] = tomllib.load(f)
    return data


@pytest.fixture
def raw_content(_raw_content: dict[str, Any]) -> dict[str, Any]:
    """A mutable deep copy of the repo's world-gen TOML data, for invalid-content tests."""
    return copy.deepcopy(_raw_content)
