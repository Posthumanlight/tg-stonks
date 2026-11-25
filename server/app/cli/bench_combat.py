"""Engine benchmark: seeded random fights, timing every player turn.

Usage, from the repo root:  poetry run python server/app/cli/bench_combat.py [--fights N]

A "turn" is what the combat worker does per intent: `apply_action` (which also
computes the next unit's legal actions). Budget: p95 <= 5 ms on a 32×32 board
(docs/architecture.md "Scalability and capacity model").
"""

import argparse
import random
import statistics
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # allow running as a plain script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.combat.ground.board import Board
from app.combat.ground.engine import apply_action, legal_actions, start_combat
from app.combat.ground.policy import random_action
from app.combat.ground.ruleset import CombatRuleset, load_ruleset
from app.combat.ground.setup import CombatSetup, UnitSetup

BENCH_SETUP = CombatSetup(
    Board.filled(32, 32),
    (
        UnitSetup("line_troopers", 0, (3, 3)),
        UnitSetup("line_troopers", 0, (6, 2)),
        UnitSetup("heavy_team", 0, (4, 6)),
        UnitSetup("warden", 0, (2, 5)),
        UnitSetup("bastion_walker", 0, (1, 8)),
        UnitSetup("ravager_swarm", 1, (26, 26)),
        UnitSetup("spitter_brood", 1, (28, 24)),
        UnitSetup("spitter_brood", 1, (24, 28)),
        UnitSetup("brood_tyrant", 1, (22, 25)),
    ),
)


def turn_timings(
    ruleset: CombatRuleset, fights: int, max_actions: int = 300
) -> list[float]:
    """Seconds per turn: legal actions as sent to the client + the action itself."""
    timings: list[float] = []
    for seed in range(fights):
        rng, chooser = random.Random(seed), random.Random(seed + 1000)
        state, _ = start_combat(ruleset, BENCH_SETUP, rng)
        for _ in range(max_actions):
            if state.outcome is not None:
                break
            started = time.perf_counter()
            options = legal_actions(ruleset, state)
            action = random_action(state, options, chooser)
            state, _ = apply_action(ruleset, state, action, rng)
            timings.append(time.perf_counter() - started)
    return timings


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fights", type=int, default=20)
    args = parser.parse_args()
    ruleset = load_ruleset()
    timings = turn_timings(ruleset, args.fights)
    ms = [t * 1000 for t in timings]
    print(
        f"{len(ms)} turns over {args.fights} fights: "
        f"p50 {percentile(ms, 0.5):.2f} ms · p95 {percentile(ms, 0.95):.2f} ms · "
        f"p99 {percentile(ms, 0.99):.2f} ms · mean {statistics.fmean(ms):.2f} ms"
    )


if __name__ == "__main__":
    main()
