"""Write-behind buffer (CLAUDE.md rule 5): gameplay writes are batched, never per action.

Generic so the world sim can reuse it. Items are flushed in order; a failed flush puts
its batch back in front and retries with backoff.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")
log = logging.getLogger(__name__)

MAX_BACKOFF_S = 30.0


class WriteBehindBuffer(Generic[T]):
    def __init__(
        self,
        flush_fn: Callable[[list[T]], Awaitable[None]],
        *,
        interval_s: float = 1.0,
        max_batch: int = 500,
    ) -> None:
        self._flush_fn = flush_fn
        self._interval = interval_s
        self._max_batch = max_batch
        self._pending: list[T] = []
        self._lock = asyncio.Lock()  # one flush at a time keeps batches in order

    def __len__(self) -> int:
        return len(self._pending)

    def add(self, item: T) -> None:
        self._pending.append(item)

    def extend(self, items: list[T]) -> None:
        self._pending.extend(items)

    async def flush(self) -> None:
        """Write everything pending now. Raises if the write fails (items are kept)."""
        async with self._lock:
            while self._pending:
                batch = self._pending[: self._max_batch]
                del self._pending[: len(batch)]
                try:
                    await self._flush_fn(batch)
                except BaseException:
                    self._pending[:0] = batch
                    raise

    async def run(self) -> None:
        """Flush every `interval_s` until cancelled; back off while writes fail."""
        delay = self._interval
        while True:
            await asyncio.sleep(delay)
            try:
                await self.flush()
                delay = self._interval
            except Exception:
                delay = min(MAX_BACKOFF_S, delay * 2)
                log.exception("write-behind flush failed; retrying in %.1f s", delay)
