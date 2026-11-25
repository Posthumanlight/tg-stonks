"""A seeded random player: picks among legal actions, biased toward fighting.

Pure. Shared by the determinism tests (golden fight), the engine benchmark and the
load-test bots, so they all exercise the engine the same way. Changing this changes
the golden-fight hash.
"""

import random

from app.combat.ground.actions import Action, Attack, Move, Skip, UseAbility, Wait
from app.combat.ground.engine import LegalActions
from app.combat.ground.state import CombatState


def random_action(
    state: CombatState, options: LegalActions, chooser: random.Random
) -> Action:
    choices: list[Action] = [Attack(a.weapon, a.target) for a in options.attacks] * 3
    for ability in options.abilities:
        if ability.target_units:
            choices.append(
                UseAbility(ability.ability, target_unit=ability.target_units[0])
            )
        else:
            choices.append(
                UseAbility(ability.ability, target_square=ability.target_squares[-1])
            )
    if options.moves:
        me = state.unit(options.unit)
        enemies = [u for u in state.living() if u.side != me.side]
        best = min(
            options.moves,
            key=lambda m: min(
                abs(m.destination[0] - e.origin[0])
                + abs(m.destination[1] - e.origin[1])
                for e in enemies
            ),
        )
        choices += [Move(best.path)] * 2
    if options.can_wait:
        choices.append(Wait())
    choices.append(Skip())
    return chooser.choice(choices)
