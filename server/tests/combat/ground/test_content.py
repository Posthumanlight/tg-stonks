import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.combat.ground.ruleset import RulesetError, ruleset_from_raw
from app.config import REPO_ROOT
from app.content.combat import parse_combat_content


def test_repo_content_compiles(ruleset) -> None:
    assert ruleset.unit_abilities["line_troopers"]
    assert {b.ability_id for b in ruleset.weapon_abilities["rail_lance"]} == {
        "heavy",
        "anti",
    }
    assert set(ruleset.statuses) == {"disengage"}
    assert len(ruleset.content_hash) == 64


def test_every_ability_is_used_or_a_status(ruleset) -> None:
    """Unreferenced abilities with params would never be compiled, so forbid them."""
    content = ruleset.content
    used = {r.id for w in content.weapons.values() for r in w.abilities}
    used |= {r.id for u in content.units.values() for r in u.abilities}
    for aid, ability in content.abilities.items():
        assert aid in used or ability.kind == "status", f"ability {aid!r} is never used"


def _player_keys(content: Any) -> set[str]:
    keys = set()
    for group in (
        content.factions,
        content.terrain,
        content.overlays,
        content.weapon_types,
        content.weapons,
        content.units,
    ):
        keys |= {item.name_key for item in group.values()}
    for ability in content.abilities.values():
        keys.add(ability.name_key)
        if ability.description_key:
            keys.add(ability.description_key)
        for trigger in ability.triggers:
            for call in trigger.actions:
                if "reason_key" in call.args:
                    keys.add(call.args["reason_key"])
    return keys


ENGINE_KEYS = (
    {
        f"attack.forbidden.{k}"
        for k in (
            "target_dead",
            "friendly",
            "no_carrier",
            "not_active",
            "weapon_used",
            "not_enough_ap",
            "first_round",
            "out_of_range",
            "no_los",
        )
    }
    | {
        f"ability.forbidden.{k}"
        for k in (
            "not_active",
            "unknown",
            "not_enough_ap",
            "on_cooldown",
            "no_uses",
            "bad_target",
            "out_of_range",
            "no_los",
        )
    }
    | {f"move.forbidden.{k}" for k in ("after_attack", "empty", "blocked", "too_far")}
    | {
        "wait.forbidden",
        "combat.forbidden.over",
        "combat.forbidden.no_active_unit",
        "combat.forbidden.unknown_action",
    }
)


@pytest.mark.parametrize("locale", ["en.json", "ua.json"])
def test_every_player_facing_key_is_localized(ruleset, locale: str) -> None:
    keys = set(json.loads((REPO_ROOT / "locales" / locale).read_text(encoding="utf-8")))
    missing = (_player_keys(ruleset.content) | ENGINE_KEYS) - keys
    assert missing == set()


# --- invalid content ---------------------------------------------------------------------


def _trigger(raw: dict, ability: str, index: int = 0) -> dict:
    return raw["abilities"][ability]["triggers"][index]


def test_unknown_function(raw) -> None:
    _trigger(raw, "assault")["actions"] = [{"fn": "no_such_fn"}]
    with pytest.raises(RulesetError, match="unknown function"):
        ruleset_from_raw(raw)


def test_action_used_as_condition(raw) -> None:
    _trigger(raw, "heavy")["conditions"] = [{"fn": "keep_movement"}]
    with pytest.raises(RulesetError, match="registered as action, used as condition"):
        ruleset_from_raw(raw)


def test_function_in_wrong_event(raw) -> None:
    _trigger(raw, "assault")["event"] = "damage_calculating"
    with pytest.raises(RulesetError, match="can't be hooked into"):
        ruleset_from_raw(raw)


def test_unknown_event(raw) -> None:
    _trigger(raw, "assault")["event"] = "on_tuesday"
    with pytest.raises(RulesetError, match="unknown event"):
        ruleset_from_raw(raw)


def test_bad_function_param(raw) -> None:
    _trigger(raw, "anti")["actions"] = [{"fn": "multiply_damage", "percent": "lots"}]
    with pytest.raises(RulesetError, match="multiply_damage"):
        ruleset_from_raw(raw)


def test_unknown_function_param(raw) -> None:
    _trigger(raw, "assault")["actions"] = [{"fn": "keep_movement", "extra": 1}]
    with pytest.raises(RulesetError):
        ruleset_from_raw(raw)


def test_missing_ability_param(raw) -> None:
    raw["weapons"]["rail_lance"]["abilities"] = [{"id": "anti", "armor": "vehicle"}]
    with pytest.raises(RulesetError, match="missing params"):
        ruleset_from_raw(raw)


def test_wrong_ability_param_type(raw) -> None:
    raw["weapons"]["rail_lance"]["abilities"] = [
        {"id": "anti", "armor": "plasma", "percent": 150}
    ]
    with pytest.raises(RulesetError, match="unknown armor"):
        ruleset_from_raw(raw)


def test_unknown_param_reference(raw) -> None:
    _trigger(raw, "anti")["actions"] = [{"fn": "multiply_damage", "percent": "$nope"}]
    with pytest.raises(RulesetError, match=r"\$nope"):
        ruleset_from_raw(raw)


def test_unknown_status_id(raw) -> None:
    raw["abilities"]["fall_back"]["on_cast"] = [
        {"fn": "apply_status_to_owner", "status": "flying", "rounds": 1}
    ]
    with pytest.raises(RulesetError, match="unknown status"):
        ruleset_from_raw(raw)


def test_combinator_needs_conditions(raw) -> None:
    _trigger(raw, "indirect", 1)["conditions"] = [{"fn": "not"}]
    with pytest.raises(RulesetError, match="conditions"):
        ruleset_from_raw(raw)


def test_unknown_ability_reference(raw) -> None:
    raw["units"]["warden"]["abilities"] = ["levitate"]
    with pytest.raises(ValidationError, match="unknown ability"):
        parse_combat_content(raw)


def test_weapon_ability_on_unit(raw) -> None:
    raw["units"]["warden"]["abilities"] = ["assault"]
    with pytest.raises(ValidationError, match="is 'weapon'"):
        parse_combat_content(raw)


def test_incomplete_damage_table(raw) -> None:
    del raw["damage_table"]["blade"]["monster"]
    with pytest.raises(ValidationError, match="damage_table"):
        parse_combat_content(raw)


def test_melee_weapon_with_range(raw) -> None:
    raw["weapons"]["talons"]["range"] = [1, 3]
    with pytest.raises(ValidationError, match="melee"):
        parse_combat_content(raw)


def test_two_fill_groups(raw) -> None:
    raw["units"]["line_troopers"]["groups"][1]["fill"] = True
    with pytest.raises(ValidationError, match="fill"):
        parse_combat_content(raw)


def test_unknown_weapon_in_group(raw) -> None:
    raw["units"]["warden"]["groups"][0]["weapons"] = ["laser_sword"]
    with pytest.raises(ValidationError, match="unknown weapons"):
        parse_combat_content(raw)


def test_unit_over_model_cap(raw) -> None:
    raw["units"]["ravager_swarm"]["models"]["max"] = 500
    with pytest.raises(ValidationError, match="max_models_per_unit"):
        parse_combat_content(raw)


def test_bad_dice(raw) -> None:
    raw["weapons"]["talons"]["damage"] = "D1"
    with pytest.raises(ValidationError):
        parse_combat_content(raw)
