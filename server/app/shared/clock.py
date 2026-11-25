"""Injected time. Services take a `Clock`, so tests can move time with `FakeClock`."""

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Wall-clock seconds since the epoch (token `iat`/`exp`, DB timestamps)."""
        ...

    def monotonic(self) -> float:
        """Monotonic seconds (rate limits, timeouts, intervals)."""
        ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self._now = start
        self._monotonic = 0.0

    def now(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float, *, monotonic: bool = True) -> None:
        """Move time forward. `monotonic=False` moves only the wall clock (e.g. token
        expiry without tripping idle timeouts)."""
        self._now += seconds
        if monotonic:
            self._monotonic += seconds
