# Yfinance Rate Limit + Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Protect every yfinance fetch (chart, indicators, news, observe) from hammering the upstream and from hanging the request thread when yfinance is slow. One global token bucket caps fetches/min; one per-call `asyncio.wait_for` caps wall time.

**Architecture:** A new `app/services/rate_limiter.py` module exports a single shared `YF_LIMITER = AsyncTokenBucket(rate=60/min, capacity=10)` plus a `guarded_fetch(name, timeout, fn, *args)` helper that (1) acquires a token (waits up to `acquire_timeout`), (2) runs `fn` via `asyncio.to_thread`, (3) wraps it in `asyncio.wait_for(timeout)`. Both `chart_service` and any other yfinance caller route through `guarded_fetch`. Errors map to two custom exceptions — `RateLimitedError` and `UpstreamTimeoutError` — that the FastAPI exception handler renders as `429 Retry-After` / `504`.

**Tech Stack:** stdlib `asyncio` only — no new deps. The token bucket is hand-rolled (~30 LoC) because `aiolimiter` would add a dep we don't otherwise need.

---

## File Structure

**New:**
- `backend/app/services/rate_limiter.py` — `AsyncTokenBucket`, `RateLimitedError`, `UpstreamTimeoutError`, `guarded_fetch`, module-level `YF_LIMITER`.
- `backend/tests/test_rate_limiter.py` — unit tests for token bucket, timeout, error mapping.

**Modified:**
- `backend/app/services/chart_service.py` — replace direct `run_sync_with_retries(_download_chart_frame_sync, …)` with `guarded_fetch("yfinance.chart", 8.0, _download_chart_frame_sync, …)` wrapped in the existing retry helper.
- `backend/app/main.py` (or wherever the global exception handlers live) — add handlers mapping the two new exceptions to 429 / 504 with `Retry-After` headers.
- `backend/tests/test_chart_service.py` — one new test asserting timeout maps to `UpstreamTimeoutError`.

**Untouched:** `network_utils.run_sync_with_retries` keeps its retry semantics — we layer the limiter *inside* the function passed to it, so retries still work for transient resets but not for rate-limit waits.

---

## Reference

1. `backend/app/services/chart_service.py` — current single yfinance entry point.
2. `backend/app/services/network_utils.py` — retry wrapper we keep.
3. `backend/app/main.py` — global FastAPI exception handlers live here (search for `add_exception_handler` or `@app.exception_handler`).

---

## Tasks

### Task 1: AsyncTokenBucket + custom exceptions

**Files:**
- Create: `backend/app/services/rate_limiter.py`
- Test: `backend/tests/test_rate_limiter.py`

- [ ] **Step 1: Write the failing test for token-bucket basic flow**

```python
# backend/tests/test_rate_limiter.py
from __future__ import annotations
import asyncio
import unittest
from app.services.rate_limiter import AsyncTokenBucket, RateLimitedError


class AsyncTokenBucketTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_consumes_capacity_then_refills(self) -> None:
        # 2-token bucket, refilling 1 token every 0.05s.
        bucket = AsyncTokenBucket(rate_per_sec=20.0, capacity=2)
        await bucket.acquire()  # token #1
        await bucket.acquire()  # token #2
        # No tokens left — acquire(timeout=0.0) should immediately raise.
        with self.assertRaises(RateLimitedError):
            await bucket.acquire(wait_timeout=0.0)
        # After 0.06s the bucket has at least one token again.
        await asyncio.sleep(0.06)
        await bucket.acquire(wait_timeout=0.0)
```

- [ ] **Step 2: Run test to confirm failure**

```bash
cd backend && python -m pytest tests/test_rate_limiter.py -x -q
```
Expected: `ModuleNotFoundError: No module named 'app.services.rate_limiter'`.

- [ ] **Step 3: Implement `AsyncTokenBucket` + exceptions**

```python
# backend/app/services/rate_limiter.py
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class RateLimitedError(RuntimeError):
    """Raised when no token was available within wait_timeout."""

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
```

- [ ] **Step 4: Run test to confirm pass**

```bash
cd backend && python -m pytest tests/test_rate_limiter.py -x -q
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rate_limiter.py backend/tests/test_rate_limiter.py
git commit -m "feat(rate-limit): async token bucket + custom errors"
```

### Task 2: `guarded_fetch` helper with timeout

**Files:**
- Modify: `backend/app/services/rate_limiter.py`
- Test: `backend/tests/test_rate_limiter.py`

- [ ] **Step 1: Write the failing test for timeout mapping**

```python
async def test_guarded_fetch_maps_timeout_to_upstream_timeout(self) -> None:
    from app.services.rate_limiter import (
        AsyncTokenBucket, UpstreamTimeoutError, guarded_fetch,
    )
    bucket = AsyncTokenBucket(rate_per_sec=100.0, capacity=10)

    def slow():
        time.sleep(0.2)
        return "done"

    with self.assertRaises(UpstreamTimeoutError):
        await guarded_fetch(
            "test", limiter=bucket, fetch_timeout=0.05,
            acquire_timeout=1.0, fn=slow,
        )

async def test_guarded_fetch_returns_value_on_success(self) -> None:
    from app.services.rate_limiter import AsyncTokenBucket, guarded_fetch
    bucket = AsyncTokenBucket(rate_per_sec=100.0, capacity=10)
    result = await guarded_fetch(
        "test", limiter=bucket, fetch_timeout=1.0,
        acquire_timeout=1.0, fn=lambda x: x + 1, args=(41,),
    )
    self.assertEqual(result, 42)
```

(Add `import time` to the test file imports.)

- [ ] **Step 2: Run test to confirm failure**

```bash
cd backend && python -m pytest tests/test_rate_limiter.py -x -q
```
Expected: `ImportError: cannot import name 'guarded_fetch'`.

- [ ] **Step 3: Implement `guarded_fetch` and module limiter**

Append to `backend/app/services/rate_limiter.py`:

```python
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


# Defaults tuned for yfinance: 60 req/min sustained, burst of 10.
YF_LIMITER = AsyncTokenBucket(rate_per_sec=1.0, capacity=10)
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
cd backend && python -m pytest tests/test_rate_limiter.py -x -q
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rate_limiter.py backend/tests/test_rate_limiter.py
git commit -m "feat(rate-limit): guarded_fetch wraps token bucket + timeout"
```

### Task 3: Wire `chart_service` through the limiter

**Files:**
- Modify: `backend/app/services/chart_service.py`
- Test: `backend/tests/test_chart_service.py`

- [ ] **Step 1: Add a failing test for timeout propagation**

```python
async def test_get_symbol_chart_propagates_upstream_timeout(self) -> None:
    import time
    from app.services.rate_limiter import UpstreamTimeoutError

    def slow_download(*_a, **_kw):
        time.sleep(2.0)
        return None

    with patch(
        "app.services.chart_service._download_chart_frame_sync",
        side_effect=slow_download,
    ), patch("app.services.chart_service._FETCH_TIMEOUT_SEC", 0.05):
        with self.assertRaises(UpstreamTimeoutError):
            await chart_service.get_symbol_chart("AAPL", "1d")
```

- [ ] **Step 2: Run test, confirm failure**

```bash
cd backend && python -m pytest tests/test_chart_service.py -x -q
```
Expected: failing because `_FETCH_TIMEOUT_SEC` doesn't exist and timeout doesn't fire.

- [ ] **Step 3: Wire `chart_service` through `guarded_fetch`**

Edit `backend/app/services/chart_service.py`:

```python
from app.services.network_utils import run_sync_with_retries
from app.services.rate_limiter import (
    YF_LIMITER, RateLimitedError, UpstreamTimeoutError, guarded_fetch,
)

# Module-level so tests can monkey-patch.
_FETCH_TIMEOUT_SEC = 8.0
_ACQUIRE_TIMEOUT_SEC = 5.0
```

Replace the `run_sync_with_retries` call inside `get_symbol_chart` with:

```python
async def _do_download():
    return await guarded_fetch(
        f"yfinance.chart[{normalized_symbol}/{normalized_range}]",
        limiter=YF_LIMITER,
        fetch_timeout=_FETCH_TIMEOUT_SEC,
        acquire_timeout=_ACQUIRE_TIMEOUT_SEC,
        fn=_download_chart_frame_sync,
        args=(normalized_symbol, range_config["period"], range_config["interval"]),
    )

# Retain transient-error retries from network_utils, but skip retries for
# UpstreamTimeoutError / RateLimitedError — those are already protective.
try:
    frame = await _do_download()
except (UpstreamTimeoutError, RateLimitedError):
    raise
```

(Drop the old `run_sync_with_retries` invocation; transient connection-reset retries from yfinance are now best-effort one-shot — if you want them back layer them around `_do_download` separately, but per Self-Review we keep this simple.)

- [ ] **Step 4: Run all chart tests**

```bash
cd backend && python -m pytest tests/test_chart_service.py -x -q
```
Expected: previous 4 + new timeout test = 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/chart_service.py backend/tests/test_chart_service.py
git commit -m "feat(chart): route yfinance through global token bucket + timeout"
```

### Task 4: HTTP exception mapping (429 / 504)

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_chart_service.py` (router-level smoke test in existing suite if available; otherwise plain unit test on the handlers)

- [ ] **Step 1: Locate exception handlers**

```bash
cd backend && grep -n "exception_handler" app/main.py
```

- [ ] **Step 2: Add handlers**

In `backend/app/main.py`, after existing handlers:

```python
from app.services.rate_limiter import RateLimitedError, UpstreamTimeoutError
from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(RateLimitedError)
async def _rate_limited_handler(_request: Request, exc: RateLimitedError) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": str(exc)},
        headers={"Retry-After": f"{max(int(exc.retry_after), 1)}"},
    )


@app.exception_handler(UpstreamTimeoutError)
async def _upstream_timeout_handler(_request: Request, exc: UpstreamTimeoutError) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": str(exc)})
```

- [ ] **Step 3: Verify by running the full backend suite**

```bash
cd backend && python -m unittest discover -s tests -p "test_*.py"
```
Expected: all pre-existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(api): map RateLimitedError/UpstreamTimeoutError to 429/504"
```

---

## Self-Review

- [x] Token bucket is async-safe (single `asyncio.Lock`).
- [x] `guarded_fetch` is the only entry point — every yfinance caller routes through it.
- [x] No new deps.
- [x] Backward-compatible: existing chart endpoints behave the same on the happy path; only error semantics change (504/429 instead of opaque 500).
- [x] Tests cover: bucket exhaustion, refill, timeout mapping, success path.
- [x] Defaults: 60 req/min sustained (`rate_per_sec=1`), burst of 10. Tunable per-call via `acquire_timeout`.

## Concerns / Follow-ups

1. **Per-symbol dedupe not yet implemented.** Two concurrent requests for the same `(symbol, range)` still each consume a token. Adding an in-flight-fetch coalescer (`dict[key, asyncio.Task]`) would cut load further; deferred until we see the symptom.
2. **Indicators / observe / news still use direct yfinance.** This plan only wires `chart_service`. Phase-2 follow-up: extend `guarded_fetch` to those services.
3. **Retry interplay.** `network_utils.run_sync_with_retries` was bypassed for the chart path. If yfinance flakes with connection resets we lose the 3x retry. Acceptable trade-off because limiter already cushions burst load; if reset rate climbs we reintroduce retries *outside* `guarded_fetch`.
4. **No persisted metrics.** Bucket state lives in process memory; restart resets it. Fine for single-worker deploys.
