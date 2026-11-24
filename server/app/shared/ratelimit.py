"""Token buckets: one implementation for auth limits and per-WebSocket limits.

In-memory, which is correct because the gateway is a single process
(docs/architecture.md "Rate limits").
"""

from collections import OrderedDict
from collections.abc import Hashable

from app.shared.clock import Clock


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: int, clock: Clock) -> None:
        if rate_per_s <= 0 or burst < 1:
            raise ValueError("rate must be > 0 and burst >= 1")
        self.rate = rate_per_s
        self.burst = burst
        self._clock = clock
        self._tokens = float(burst)
        self._last = clock.monotonic()

    def _refill(self) -> None:
        now = self._clock.monotonic()
        self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
        self._last = now

    def take(self, amount: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= amount:
            self._tokens -= amount
            return True
        return False

    def retry_after(self, amount: float = 1.0) -> float:
        """Seconds until `amount` tokens are available (0 if they are now)."""
        self._refill()
        return max(0.0, (amount - self._tokens) / self.rate)


class KeyedRateLimiter:
    """One bucket per key (IP, username, …); least recently used keys are evicted."""

    def __init__(
        self, rate_per_s: float, burst: int, clock: Clock, *, max_keys: int = 10_000
    ) -> None:
        self.rate, self.burst, self._clock = rate_per_s, burst, clock
        self._max_keys = max_keys
        self._buckets: OrderedDict[Hashable, TokenBucket] = OrderedDict()

    @classmethod
    def per_minute(cls, limit: int, clock: Clock) -> "KeyedRateLimiter":
        return cls(limit / 60, limit, clock)

    @classmethod
    def per_hour(cls, limit: int, clock: Clock) -> "KeyedRateLimiter":
        return cls(limit / 3600, limit, clock)

    def hit(self, key: Hashable) -> float | None:
        """Consume one token for `key`. None if allowed, else seconds to wait."""
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(self.rate, self.burst, self._clock)
            self._buckets[key] = bucket
            if len(self._buckets) > self._max_keys:
                self._buckets.popitem(last=False)
        else:
            self._buckets.move_to_end(key)
        if bucket.take():
            return None
        return bucket.retry_after()
