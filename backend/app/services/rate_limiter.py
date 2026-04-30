"""Async token-bucket limiter + timeout-guarded fetch.

Used to protect outbound yfinance / scraping calls from runaway concurrency
and from hanging on slow upstream responses. Exposed as a single shared
``YF_LIMITER`` plus a thin ``guarded_fetch`` helper.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class RateLimitedError(RuntimeError):
    """Raised when no token was available within ``wait_timeout``."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UpstreamTimeoutError(RuntimeError):
    """Raised when an upstream fetch exceeded its wall-clock budget."""


class AsyncTokenBucket:
    """Lazy-refill token bucket. Safe across coroutines via a single lock."""

    def __init__(self, rate_per_sec: float, capacity: int) -> None:
        if rate_per_sec <= 0 or capacity <= 0:
            raise ValueError("rate_per_sec and capacity must be positive")
        self._rate = float(rate_per_sec)
        self._capacity = int(capacity)
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill_locked(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last = now

    async def acquire(self, wait_timeout: float | None = None) -> None:
        deadline = None if wait_timeout is None else time.monotonic() + wait_timeout
        while True:
            async with self._lock:
                self._refill_locked()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                missing = 1.0 - self._tokens
                wait_for = missing / self._rate
            if deadline is not None and time.monotonic() + wait_for > deadline:
                raise RateLimitedError(
                    "Upstream rate limit reached; retry after a moment.",
                    retry_after=max(wait_for, 0.0),
                )
            await asyncio.sleep(min(wait_for, 0.5))


async def guarded_fetch(
    name: str,
    *,
    limiter: AsyncTokenBucket,
    fetch_timeout: float,
    acquire_timeout: float,
    fn: Callable[..., T],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> T:
    """Acquire a token, then run ``fn`` in a thread with a wall-clock cap."""
    await limiter.acquire(wait_timeout=acquire_timeout)
    coro: Awaitable[T] = asyncio.to_thread(fn, *args, **(kwargs or {}))
    try:
        return await asyncio.wait_for(coro, timeout=fetch_timeout)
    except asyncio.TimeoutError as exc:
        raise UpstreamTimeoutError(
            f"{name} exceeded {fetch_timeout:.1f}s budget"
        ) from exc


# Defaults tuned for yfinance: ~60 fetches/min sustained, burst of 10.
YF_LIMITER = AsyncTokenBucket(rate_per_sec=1.0, capacity=10)
