import copy
from typing import Any

import pytest

from app.combat.ground.ruleset import CombatRuleset, load_ruleset
from app.content.combat import load_raw_combat_content


@pytest.fixture(scope="session")
def ruleset() -> CombatRuleset:
    return load_ruleset()


@pytest.fixture(scope="session")
def _raw() -> dict[str, Any]:
    return load_raw_combat_content()


@pytest.fixture
def raw(_raw: dict[str, Any]) -> dict[str, Any]:
    """A mutable deep copy of the repo's combat content."""
    return copy.deepcopy(_raw)
