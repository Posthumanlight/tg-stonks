"""Engine performance guard (docs/architecture.md "Scalability and capacity model").

The real budget (p95 <= 8 ms per turn on 32×32) is checked with
`server/app/cli/bench_combat.py` on a dev box. This test uses a generous bound so slow
CI machines don't flake, but still catches order-of-magnitude regressions.
"""

import pytest

from app.cli.bench_combat import percentile, turn_timings

CI_P95_BOUND_MS = 40


@pytest.mark.perf
def test_turn_cost_stays_in_budget(ruleset) -> None:
    turn_timings(ruleset, 1)  # warm the geometry caches
    timings_ms = [t * 1000 for t in turn_timings(ruleset, 4)]
    assert percentile(timings_ms, 0.95) < CI_P95_BOUND_MS
