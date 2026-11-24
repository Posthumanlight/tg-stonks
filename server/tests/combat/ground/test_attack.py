from fractions import Fraction

import pytest

from app.combat.ground.actions import Attack
from app.combat.ground.attack import resolve_hits
from app.combat.ground.dice import Dice
from app.combat.ground.engine import IllegalAction, apply_action, legal_actions
from app.combat.ground.ruleset import ruleset_from_raw

from .helpers import activate, board, resolver, start


def test_no_spill_and_wounded_model_first(ruleset) -> None:
    state, _, _ = start(ruleset, [("warden", 0, (0, 0)), ("heavy_team", 1, (5, 5))])
    res = resolver(ruleset, state)
    assert res.apply_damage(1, 2, source=0, weapon=None) == (2, None)
    assert res.state.unit(1).wounded == (0, 1)
    # 5 damage on the wounded model: 1 applied, the excess is lost
    assert res.apply_damage(1, 5, source=0, weapon=None) == (1, "gunner")
    unit = res.state.unit(1)
    assert unit.wounded is None and unit.models == 2
    assert res.apply_damage(1, 1, source=0, weapon=None) == (1, None)
    assert res.state.unit(1).wounded == (0, 2)  # a fresh gunner


def test_casualty_priority(ruleset) -> None:
    state, _, _ = start(ruleset, [("warden", 0, (0, 0)), ("line_troopers", 1, (5, 5))])
    res = resolver(ruleset, state)
    roles = [res.apply_damage(1, 9, source=0, weapon=None)[1] for _ in range(10)]
    assert roles == ["trooper"] * 8 + ["gunner", "sergeant"]
    assert not res.state.unit(1).alive
    assert [e.kind for e in res.events].count("unit_destroyed") == 1
    assert res.apply_damage(1, 3, source=0, weapon=None) == (0, None)


def test_kills_never_exceed_hits(ruleset) -> None:
    state, _, _ = start(ruleset, [("warden", 0, (0, 0)), ("ravager_swarm", 1, (1, 1))])
    for seed in range(20):
        res = resolver(ruleset, state, seed=seed)
        total, kills = resolve_hits(
            res,
            0,
            1,
            3,
            Dice.parse("D3+3"),
            "blade",
            False,
            cover=False,
            weapon="shock_maul",
        )
        assert kills == 3 and total == 3  # each hit kills exactly one 1-HP model


def _mean_damage(ruleset, state, *, cover: bool, dice: str, n: int = 3000) -> Fraction:
    res = resolver(ruleset, state, seed=3)
    total = 0
    for _ in range(n):
        res.state = state
        t, _ = resolve_hits(
            res, 0, 1, 1, Dice.parse(dice), "heavy", True, cover=cover, weapon=None
        )
        total += t
    return Fraction(total, n)


def test_cover_halves_expected_damage(ruleset) -> None:
    state, _, _ = start(ruleset, [("warden", 0, (0, 0)), ("bastion_walker", 1, (6, 6))])
    # heavy vs vehicle = 75%: open mean = 5.5 × 0.75; cover halves it
    open_mean = _mean_damage(ruleset, state, cover=False, dice="D6+2")
    cover_mean = _mean_damage(ruleset, state, cover=True, dice="D6+2")
    assert abs(open_mean - Fraction(33, 8)) < Fraction(1, 5)
    assert abs(cover_mean / open_mean - Fraction(1, 2)) < Fraction(1, 20)


def test_cover_on_one_damage_weapons_is_a_coin_flip(ruleset) -> None:
    state, _, _ = start(ruleset, [("warden", 0, (0, 0)), ("bastion_walker", 1, (6, 6))])
    res = resolver(ruleset, state, seed=8)
    results = []
    for _ in range(2000):
        res.state = state
        # 2 × 100% × ½ = 1 exactly; then 1 × 75% × ½ = 3/8 → stochastic
        t, _ = resolve_hits(
            res, 0, 1, 1, Dice.parse("1"), "heavy", True, cover=True, weapon=None
        )
        results.append(t)
    assert set(results) == {0, 1}
    assert abs(Fraction(sum(results), len(results)) - Fraction(3, 8)) < Fraction(1, 25)


def test_damage_table_applies(ruleset) -> None:
    state, _, _ = start(ruleset, [("warden", 0, (0, 0)), ("bastion_walker", 1, (6, 6))])
    res = resolver(ruleset, state, seed=1)
    totals = []
    for _ in range(400):
        res.state = state
        totals.append(
            resolve_hits(
                res,
                0,
                1,
                1,
                Dice.parse("4"),
                "small_arms",
                True,
                cover=False,
                weapon=None,
            )[0]
        )
    assert set(totals) == {1}  # 4 × 25% = 1 exactly


def test_redirected_hits_use_the_victims_armor_and_cover(ruleset) -> None:
    # bodyguard (heavy team, in forest) next to the warden (open ground)
    rows = ["." * 12] * 12
    rows[2] = "...f........"
    units = [
        ("warden", 0, (2, 2)),
        ("heavy_team", 0, (3, 2)),
        ("line_troopers", 1, (2, 7)),
    ]
    state, _, _ = start(ruleset, units, board_=board(rows))
    res = resolver(ruleset, state)
    assert not res.cover_for(2, 0)  # the warden has no cover from the shooter
    resolve_hits(
        res,
        2,
        0,
        3,
        Dice.parse("4"),
        "small_arms",
        True,
        cover=res.cover_for(2, 0),
        weapon=None,
    )
    hits = [e for e in res.events if e.kind == "hit_resolved"]
    # 4 × small arms vs heavy (50%) × area cover (½) = 1; against the warden it would be 4
    assert [(e.target, e.damage, e.cover) for e in hits] == [(1, 1, True)] * 3


def test_engaged_units_can_shoot(ruleset) -> None:
    state, _, _ = start(
        ruleset, [("heavy_team", 0, (3, 3)), ("ravager_swarm", 1, (4, 3))]
    )
    state = activate(ruleset, state, 0)
    options = legal_actions(ruleset, state)
    weapons = {(a.weapon, a.target) for a in options.attacks}
    assert ("pulse_rifle", 1) in weapons  # ranged weapon at an adjacent enemy
    assert ("combat_knife", 1) in weapons
    assert ("autocannon", 1) not in weapons  # min range 2


def test_attack_rules(ruleset) -> None:
    units = [
        ("line_troopers", 0, (0, 0)),
        ("warden", 0, (0, 2)),
        ("brood_tyrant", 1, (9, 9)),
    ]
    state, _, rng = start(ruleset, units)
    state = activate(ruleset, state, 0)
    with pytest.raises(IllegalAction, match="friendly"):
        apply_action(ruleset, state, Attack("pulse_rifle", 1), rng, strict=True)
    with pytest.raises(IllegalAction, match="no_carrier"):
        apply_action(ruleset, state, Attack("mortar", 2), rng, strict=True)
    with pytest.raises(IllegalAction, match="out_of_range"):
        apply_action(ruleset, state, Attack("combat_knife", 2), rng, strict=True)
    state, _ = apply_action(ruleset, state, Attack("pulse_rifle", 2), rng, strict=True)
    assert state.active.ap_left == 1
    with pytest.raises(IllegalAction, match="weapon_used"):
        apply_action(ruleset, state, Attack("pulse_rifle", 2), rng, strict=True)
    with pytest.raises(IllegalAction, match="not_enough_ap"):
        apply_action(ruleset, state, Attack("rail_lance", 2), rng, strict=True)


def test_illegal_action_leaves_rng_untouched(ruleset) -> None:
    state, _, rng = start(
        ruleset, [("line_troopers", 0, (0, 0)), ("brood_tyrant", 1, (9, 9))]
    )
    state = activate(ruleset, state, 0)
    before = rng.getstate()
    with pytest.raises(IllegalAction):
        apply_action(ruleset, state, Attack("combat_knife", 1), rng, strict=True)
    assert rng.getstate() == before


def test_first_round_no_attacks(raw) -> None:
    raw["rules"]["first_round_no_attacks"] = True
    rs = ruleset_from_raw(raw)
    state, _, rng = start(
        rs, [("line_troopers", 0, (0, 0)), ("brood_tyrant", 1, (9, 9))]
    )
    state = activate(rs, state, 0)
    with pytest.raises(IllegalAction, match="first_round"):
        apply_action(rs, state, Attack("pulse_rifle", 1), rng, strict=True)


def test_ranged_attack_needs_los(ruleset) -> None:
    from .helpers import board

    rows = ["........"] * 8
    rows[0] = "...#...."
    state, _, rng = start(
        ruleset,
        [("line_troopers", 0, (0, 0)), ("warden", 1, (6, 0))],
        board_=board(rows),
    )
    state = activate(ruleset, state, 0)
    with pytest.raises(IllegalAction, match="no_los"):
        apply_action(ruleset, state, Attack("pulse_rifle", 1), rng, strict=True)
