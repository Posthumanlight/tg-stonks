"""Every i18n key that world-gen content references must exist in every locale file."""

import json

import pytest

from app.config import REPO_ROOT
from app.content.worldgen import WorldgenContent

LOCALES_DIR = REPO_ROOT / "locales"
LOCALE_FILES = ("en.json", "ua.json")


def _keys(name: str) -> set[str]:
    return set(json.loads((LOCALES_DIR / name).read_text(encoding="utf-8")))


@pytest.mark.parametrize("locale_file", LOCALE_FILES)
def test_content_name_keys_exist(content: WorldgenContent, locale_file: str) -> None:
    referenced = {t.name_key for t in content.planets.types.values()} | {
        c.name_key for c in content.resources.categories
    }
    assert referenced - _keys(locale_file) == set()


def test_locales_have_the_same_keys() -> None:
    first, *rest = (_keys(name) for name in LOCALE_FILES)
    for other in rest:
        assert other == first
