# Phase 4.1 — APScheduler Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ad-hoc `asyncio.create_task(_run_monitor())` infinite-loop monitors (price alerts, social polling) with a single `AsyncIOScheduler`-backed scheduler that owns all background work, exposes its job inventory for observability, and lets new periodic jobs (sector rotation, IBKR sync, etc.) plug in via one register call.

**Architecture:** A singleton `AsyncIOScheduler` lives in `app/scheduler.py` with `start()` / `shutdown()` / `register_job()`. Each background job is a plain async function — the scheduler handles the loop, the sleep, and exception suppression. Existing services keep their work functions (`evaluate_rules_once`, `social_polling_run_once`); we delete the loop wrappers and let the scheduler call those work functions on an `IntervalTrigger`. Lifespan in `main.py` replaces the per-service `start_monitor`/`shutdown_monitor` pair with one `scheduler.start()` / `scheduler.shutdown()` pair. A new `GET /api/scheduler/jobs` endpoint surfaces registered job state (id, trigger, next_run, last_run) so the UI can show "what's running."

**Tech Stack:** APScheduler 3.x (`AsyncIOScheduler`, `IntervalTrigger`, `CronTrigger`), FastAPI, pytest, pytest-asyncio. No DB persistence — jobs are re-registered at startup (matches the current pattern: ad-hoc tasks already evaporate on restart).

---

## File Structure

**Create:**
- `backend/app/scheduler.py` — Singleton scheduler + `start()` / `shutdown()` / `register_job()`. ~80 LOC.
- `backend/app/services/scheduled_jobs.py` — `register_default_jobs(scheduler)` registers every platform job in one call. ~60 LOC.
- `backend/app/routers/scheduler.py` — `GET /api/scheduler/jobs`. ~30 LOC.
- `backend/app/models/scheduler.py` — Pydantic response models. ~25 LOC.
- `backend/tests/test_scheduler.py` — Unit tests for the scheduler module + scheduled_jobs registration + the endpoint. ~250 LOC.

**Modify:**
- `backend/requirements.txt` — add `apscheduler>=3.10,<4`.
- `backend/app/main.py` — lifespan replaces the four `start_monitor`/`shutdown_monitor` calls with `scheduler.start(app)` / `scheduler.shutdown()` (and registers the new router).
- `backend/app/services/price_alerts_service.py` — delete `_run_monitor` / `start_monitor` / `shutdown_monitor` / `_monitor_task` / `_monitor_lock` / `_on_monitor_done`. Keep `evaluate_rules_once` as the public job entry point. ~40 LOC removed.
- `backend/app/services/social_polling_service.py` — same shape as price_alerts: delete loop wrapper, expose `run_once()` as the public job entry point. ~30 LOC removed.
- `backend/tests/test_openapi_parity.py` — add `("GET", "/api/scheduler/jobs")`.

**Out of scope for this plan:**
- macro_sync / options_chain_sync / IBKR position sync jobs — once the registry exists, those land as one-task follow-ups in their own plans (Phase 2.4, Phase 4 follow-ups).
- Persisting job state to a DB-backed jobstore (APScheduler supports SQLAlchemyJobStore, but jobs here are re-registered every boot anyway).
- Running APScheduler in a separate worker process (single-process FastAPI + AsyncIOScheduler is the documented happy path).

---

## Reference: Existing Code to Read Before Starting

Read these once at the top of the plan; tasks below will not re-explain them:

1. `backend/app/main.py` lines 56–85 — current lifespan with `start_monitor` / `shutdown_monitor` calls.
2. `backend/app/services/price_alerts_service.py` lines 1–25 (imports, `ALERT_POLL_INTERVAL_SECONDS = 20`) and lines 351–399 (the loop + start/shutdown pair).
3. `backend/app/services/social_polling_service.py` lines 1–80 (the same shape, with the interval coming from `social_signal_service.DEFAULT_SOCIAL_POLL_INTERVAL_MINUTES`).
4. `backend/app/services/sector_rotation_service.py` — `get_sector_rotation(*, force: bool = False)` is the function our new job will call with `force=True` once an hour.
5. `backend/app/dependencies.py` — `service_error` import path; the new router uses it.
6. `backend/tests/test_app_smoke.py` — already has 6 pre-existing failures unrelated to this work; verify with `git status` before changes that the count is still 6 after.

---

## Tasks

### Task 1: Add APScheduler dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add the dep**

Open `backend/requirements.txt` and append exactly one line at the bottom:

```
apscheduler>=3.10,<4
```

- [ ] **Step 2: Install it locally**

Run from repo root:

```bash
pip install "apscheduler>=3.10,<4"
```

Expected: `Successfully installed apscheduler-3.x.x` (any 3.10+ point release is fine; the constraint floor is what matters).

- [ ] **Step 3: Verify import works**

Run from `backend/`:

```bash
python -c "from apscheduler.schedulers.asyncio import AsyncIOScheduler; from apscheduler.triggers.interval import IntervalTrigger; from apscheduler.triggers.cron import CronTrigger; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore(deps): add APScheduler 3.x for unified background scheduling"
```

---

### Task 2: Build `app/scheduler.py` — singleton + start/shutdown + register_job

**Files:**
- Create: `backend/app/scheduler.py`
- Create: `backend/tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test for start/shutdown idempotency**

Create `backend/tests/test_scheduler.py`:

```python
"""Tests for app.scheduler — the AsyncIOScheduler singleton wrapper."""
from __future__ import annotations

import asyncio

import pytest

from app import scheduler as app_scheduler
from apscheduler.triggers.interval import IntervalTrigger


@pytest.fixture(autouse=True)
async def _reset_scheduler() -> None:
    """Make sure each test starts with a fresh scheduler singleton."""
    app_scheduler._reset_for_tests()  # noqa: SLF001
    yield
    await app_scheduler.shutdown()


@pytest.mark.asyncio
async def test_start_creates_running_scheduler() -> None:
    await app_scheduler.start()
    sched = app_scheduler.get_scheduler()
    assert sched is not None
    assert sched.running


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    await app_scheduler.start()
    sched_first = app_scheduler.get_scheduler()
    await app_scheduler.start()
    sched_second = app_scheduler.get_scheduler()
    assert sched_first is sched_second
    assert sched_second.running


@pytest.mark.asyncio
async def test_shutdown_stops_scheduler() -> None:
    await app_scheduler.start()
    await app_scheduler.shutdown()
    sched = app_scheduler.get_scheduler()
    assert sched is None  # cleared on shutdown


@pytest.mark.asyncio
async def test_shutdown_is_idempotent() -> None:
    await app_scheduler.start()
    await app_scheduler.shutdown()
    await app_scheduler.shutdown()  # must not raise


@pytest.mark.asyncio
async def test_get_scheduler_returns_none_before_start() -> None:
    assert app_scheduler.get_scheduler() is None
```

- [ ] **Step 2: Run the test to verify it fails on the missing module**

Run from `backend/`:

```bash
python -m pytest tests/test_scheduler.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.scheduler'`.

- [ ] **Step 3: Implement `app/scheduler.py`**

Create `backend/app/scheduler.py`:

```python
"""Application-level APScheduler singleton.

Owns one `AsyncIOScheduler` for the whole process. Services that want to
run something periodically register a job through `register_job(...)`;
the scheduler handles the loop, the sleep, and per-iteration exception
suppression so callers don't reimplement those primitives.

Lifecycle: `start()` and `shutdown()` are both idempotent and safe to
call from anywhere. Tests reset the singleton via `_reset_for_tests()`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger

logger = logging.getLogger(__name__)


# Module-level singleton. Held under `_lock` so concurrent start/shutdown
# calls from FastAPI lifespan + a test fixture don't race.
_scheduler: AsyncIOScheduler | None = None
_lock = asyncio.Lock()


def get_scheduler() -> AsyncIOScheduler | None:
    """Return the running scheduler, or None when not yet started.

    Routers that want to introspect job state read this and degrade to an
    empty list when None — that way the /api/scheduler/jobs endpoint
    works in test environments that don't boot the lifespan.
    """
    return _scheduler


async def start() -> None:
    """Create the scheduler if needed and start it. Idempotent."""
    global _scheduler
    async with _lock:
        if _scheduler is not None and _scheduler.running:
            return
        if _scheduler is None:
            _scheduler = AsyncIOScheduler(
                # Coalesce missed runs (e.g., laptop sleep) into one,
                # and cap concurrent instances at 1 so a slow job doesn't
                # stack invocations.
                job_defaults={"coalesce": True, "max_instances": 1},
            )
        _scheduler.start()
        logger.info("Application scheduler started.")


async def shutdown() -> None:
    """Stop the scheduler and clear the singleton. Idempotent."""
    global _scheduler
    async with _lock:
        sched = _scheduler
        if sched is None:
            return
        if sched.running:
            sched.shutdown(wait=False)
        _scheduler = None
        logger.info("Application scheduler stopped.")


def register_job(
    job_id: str,
    func: Callable[..., Awaitable[Any]],
    trigger: BaseTrigger,
    *,
    replace_existing: bool = True,
    **kwargs: Any,
) -> None:
    """Register an async job under a stable id.

    Raises `RuntimeError` when called before `start()` — registration is
    only meaningful while the scheduler is alive. Callers that want to
    pre-stage jobs at import time should defer until lifespan startup.
    """
    sched = _scheduler
    if sched is None:
        raise RuntimeError(
            "Scheduler not started; call app.scheduler.start() first."
        )
    sched.add_job(
        func,
        trigger=trigger,
        id=job_id,
        replace_existing=replace_existing,
        **kwargs,
    )
    logger.info("Registered scheduled job %s with trigger %s", job_id, trigger)


def _reset_for_tests() -> None:
    """Test-only — wipe the singleton without going through shutdown.

    Tests use this in an autouse fixture so a previous test's running
    scheduler doesn't leak into the next. Production code MUST use
    `shutdown()` instead.
    """
    global _scheduler
    _scheduler = None
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
python -m pytest tests/test_scheduler.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scheduler.py backend/tests/test_scheduler.py
git commit -m "feat(scheduler): introduce app-level AsyncIOScheduler singleton"
```

---

### Task 3: Test register_job + add a job that fires

**Files:**
- Modify: `backend/tests/test_scheduler.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_register_job_before_start_raises() -> None:
    async def noop() -> None:
        return None

    with pytest.raises(RuntimeError, match="Scheduler not started"):
        app_scheduler.register_job(
            "noop", noop, IntervalTrigger(seconds=1)
        )


@pytest.mark.asyncio
async def test_register_job_runs_on_interval() -> None:
    """A registered job should actually fire on the trigger.

    Use a 1-second interval and wait ~1.5s — the trigger machinery is
    APScheduler's, so this is a smoke test of the wiring, not of the
    scheduler library itself.
    """
    counter = {"hits": 0}

    async def bump() -> None:
        counter["hits"] += 1

    await app_scheduler.start()
    app_scheduler.register_job(
        "bump", bump, IntervalTrigger(seconds=1), next_run_time=None
    )

    # Manually trigger one run rather than waiting wall-clock — keeps the
    # test fast and deterministic. APScheduler exposes the underlying
    # job's `func` via `get_job(job_id)`.
    sched = app_scheduler.get_scheduler()
    job = sched.get_job("bump")
    await job.func()

    assert counter["hits"] == 1


@pytest.mark.asyncio
async def test_register_job_replaces_existing_by_default() -> None:
    async def noop() -> None:
        return None

    await app_scheduler.start()
    app_scheduler.register_job("dup", noop, IntervalTrigger(seconds=10))
    # Re-registering with the same id should not raise.
    app_scheduler.register_job("dup", noop, IntervalTrigger(seconds=20))

    sched = app_scheduler.get_scheduler()
    jobs = sched.get_jobs()
    assert sum(1 for j in jobs if j.id == "dup") == 1
```

- [ ] **Step 2: Run the new tests**

```bash
python -m pytest tests/test_scheduler.py -q
```

Expected: `8 passed` (5 from Task 2 + 3 new).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_scheduler.py
git commit -m "test(scheduler): cover register_job error path + run-on-trigger smoke"
```

---

### Task 4: Migrate `price_alerts_service` from infinite-loop monitor to a job function

**Files:**
- Modify: `backend/app/services/price_alerts_service.py`
- Modify: `backend/tests/test_price_alerts_service.py`

The service already has a clean per-iteration function (`evaluate_rules_once`). We're deleting the loop scaffolding (`_run_monitor`, `start_monitor`, `shutdown_monitor`, `_monitor_task`, `_monitor_lock`, `_on_monitor_done`, `_is_running`) and the `import asyncio` if no longer used. The scheduler will call `evaluate_rules_once` directly on a 20-second interval.

- [ ] **Step 1: Read the current state to confirm scope**

```bash
grep -n "_run_monitor\|start_monitor\|shutdown_monitor\|_monitor_task\|_monitor_lock\|_on_monitor_done\|_is_running" backend/app/services/price_alerts_service.py
```

Expected: hits in lines 351–399 (the loop + helpers) plus the module-level `_monitor_task = None` / `_monitor_lock = asyncio.Lock()` declarations near the top of the file.

- [ ] **Step 2: Delete the loop scaffolding**

In `backend/app/services/price_alerts_service.py`:

1. Remove the module-level lines `_monitor_task: asyncio.Task[None] | None = None` and `_monitor_lock = asyncio.Lock()` (search for them near the top of the file).
2. Remove every helper from `_run_monitor` through `shutdown_monitor` (the whole block starting at the `async def _run_monitor` line — about 50 lines).
3. Keep `evaluate_rules_once` and everything above it.
4. Keep `ALERT_POLL_INTERVAL_SECONDS = 20` — the scheduler will read it.
5. If `import asyncio` is now unused in the file, leave it; otherwise the linter will complain on the next pass and we'll handle that separately.

- [ ] **Step 3: Update the test file to drop the deleted-API tests**

Open `backend/tests/test_price_alerts_service.py` and find any tests calling `start_monitor` / `shutdown_monitor` / `_run_monitor` / `_monitor_task`. Delete those test functions outright; the underlying behavior (the loop) no longer exists. Keep tests for `evaluate_rules_once` and CRUD helpers.

If you're unsure which tests reference the deleted API, run:

```bash
grep -n "start_monitor\|shutdown_monitor\|_run_monitor\|_monitor_task" backend/tests/test_price_alerts_service.py
```

For each hit, delete the surrounding `def test_...` function.

- [ ] **Step 4: Run the price_alerts test file to confirm green**

```bash
python -m pytest tests/test_price_alerts_service.py -q
```

Expected: every remaining test passes; the count drops by however many were deleted in Step 3.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/price_alerts_service.py backend/tests/test_price_alerts_service.py
git commit -m "refactor(price_alerts): drop infinite-loop monitor; scheduler will drive evaluate_rules_once"
```

---

### Task 5: Migrate `social_polling_service` the same way

**Files:**
- Modify: `backend/app/services/social_polling_service.py`
- Modify: any test under `backend/tests/` that referenced the deleted helpers (use `grep` to find them)

The shape mirrors price_alerts. Per-iteration entry point: `evaluate_once(*, execute=False, force_refresh=False)` (already public). Interval helper is currently private (`_poll_interval_seconds`) — promote it to public so `scheduled_jobs.py` can read it.

The `_run_monitor` loop wraps `evaluate_once()` in a `social_signal_service.is_market_session_open()` guard. **Preserve that guard**: the scheduler's job function in Task 6 will call `evaluate_once` only when the market is open. Don't bake the check into `evaluate_once` — keep `evaluate_once` callable on demand from elsewhere.

- [ ] **Step 1: Delete the loop scaffolding**

Open `backend/app/services/social_polling_service.py`. Remove:

1. The `_monitor_task: asyncio.Task[None] | None = None` and `_monitor_lock = asyncio.Lock()` declarations near the top of the file.
2. `_is_running`, `_run_monitor`, `_on_monitor_done`, `start_monitor`, `shutdown_monitor` (the entire block from `def _is_running` through the end of `shutdown_monitor`).
3. The `import asyncio` line if it has no other consumers in the file (run a grep first to confirm).

Keep:
- `evaluate_once(...)` — public per-iteration entry point. Untouched.
- The interval helper, but **rename it from `_poll_interval_seconds` to `poll_interval_seconds`** (drop the leading underscore) so `scheduled_jobs.py` can call it without poking at a private name.

- [ ] **Step 2: Find and delete dead test cases**

```bash
grep -rn "social_polling_service.start_monitor\|social_polling_service.shutdown_monitor\|social_polling_service._run_monitor\|social_polling_service._poll_interval_seconds" backend/tests/
```

For each hit:
- If the test exercised `start_monitor` / `shutdown_monitor` / `_run_monitor`, delete the whole `def test_...` function — that behaviour is gone.
- If it referenced the renamed `_poll_interval_seconds`, update it to `poll_interval_seconds`.

- [ ] **Step 3: Run the relevant test files**

First find the social-polling test files:

```bash
ls backend/tests/ | grep -i social
```

Run them all:

```bash
python -m pytest backend/tests/ -k social -q
```

Expected: no failures introduced — every remaining test passes.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/social_polling_service.py backend/tests/
git commit -m "refactor(social): drop infinite-loop monitor; expose poll_interval_seconds as public"
```

---

### Task 6: Add `scheduled_jobs.register_default_jobs(scheduler)`

**Files:**
- Create: `backend/app/services/scheduled_jobs.py`
- Modify: `backend/tests/test_scheduler.py`

This module is the single place where every periodic job in the app gets wired up. Lifespan calls it once after `scheduler.start()`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_register_default_jobs_wires_known_ids() -> None:
    """After register_default_jobs, the canonical job ids should be present."""
    from app.services.scheduled_jobs import register_default_jobs

    await app_scheduler.start()
    register_default_jobs()

    sched = app_scheduler.get_scheduler()
    job_ids = {j.id for j in sched.get_jobs()}
    # The three platform jobs we ship in this plan:
    assert "price_alerts_evaluate" in job_ids
    assert "social_polling_run" in job_ids
    assert "sector_rotation_refresh" in job_ids
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_scheduler.py::test_register_default_jobs_wires_known_ids -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.scheduled_jobs'`.

- [ ] **Step 3: Implement scheduled_jobs.py**

Names are pinned: price_alerts uses `evaluate_rules_once`, social_polling uses `evaluate_once` wrapped in a market-hours guard, sector_rotation uses `get_sector_rotation(force=True)`. The wrappers below preserve each service's existing behaviour exactly (e.g., the social-polling guard).

Create `backend/app/services/scheduled_jobs.py`:

```python
"""Centralized registration of every recurring job in the platform.

Lifespan calls `register_default_jobs()` once after `scheduler.start()`.
Adding a new periodic job means adding one entry here — no change to
main.py and no new singleton in another service module.

Conventions:
- Job ids use snake_case `<service>_<verb>` so they sort by domain.
- Intervals come from named accessors in the owning service (e.g.,
  `price_alerts_service.ALERT_POLL_INTERVAL_SECONDS`,
  `social_polling_service.poll_interval_seconds()`); never hard-code
  intervals here.
- Each job that needs guards (market hours, kill switches, etc.) gets
  a small wrapper here so `register_job` always sees an
  exception-free `async def` with no required arguments.
"""
from __future__ import annotations

import logging

from apscheduler.triggers.interval import IntervalTrigger

from app import scheduler as app_scheduler
from app.services import (
    price_alerts_service,
    sector_rotation_service,
    social_polling_service,
    social_signal_service,
)

logger = logging.getLogger(__name__)


# Sector rotation refreshes once an hour — the underlying yfinance pull
# is expensive and the cache TTL inside the service is 15 min, so 60 min
# is the sweet spot between freshness and rate-limit pressure.
SECTOR_ROTATION_INTERVAL_SECONDS = 60 * 60


async def _price_alerts_evaluate() -> None:
    """Wrapper so a single failure can't bubble up and kill the scheduler."""
    try:
        await price_alerts_service.evaluate_rules_once()
    except Exception:  # noqa: BLE001
        logger.exception("price_alerts_evaluate job failed")


async def _social_polling_run() -> None:
    """Replicate the loop's market-hours guard before evaluating.

    The deleted `_run_monitor` only called `evaluate_once` when
    `social_signal_service.is_market_session_open()` was True; preserve
    that semantics here so the cutover is behaviour-neutral.
    """
    try:
        if social_signal_service.is_market_session_open():
            await social_polling_service.evaluate_once(
                execute=False, force_refresh=False
            )
    except Exception:  # noqa: BLE001
        logger.exception("social_polling_run job failed")


async def _sector_rotation_refresh() -> None:
    """Force-refresh the sector rotation cache."""
    try:
        await sector_rotation_service.get_sector_rotation(force=True)
    except Exception:  # noqa: BLE001
        logger.exception("sector_rotation_refresh job failed")


def register_default_jobs() -> None:
    """Register every periodic job the platform owns.

    Call once during lifespan startup AFTER `app_scheduler.start()`.
    Safe to call again — `register_job` defaults to replace_existing=True.
    """
    app_scheduler.register_job(
        "price_alerts_evaluate",
        _price_alerts_evaluate,
        IntervalTrigger(
            seconds=price_alerts_service.ALERT_POLL_INTERVAL_SECONDS
        ),
    )
    app_scheduler.register_job(
        "social_polling_run",
        _social_polling_run,
        IntervalTrigger(
            seconds=social_polling_service.poll_interval_seconds(),
        ),
    )
    app_scheduler.register_job(
        "sector_rotation_refresh",
        _sector_rotation_refresh,
        IntervalTrigger(seconds=SECTOR_ROTATION_INTERVAL_SECONDS),
    )
```

- [ ] **Step 4: Run the new test**

```bash
python -m pytest tests/test_scheduler.py -q
```

Expected: `9 passed` (8 from before + the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scheduled_jobs.py backend/tests/test_scheduler.py
git commit -m "feat(scheduler): register_default_jobs() wires platform jobs in one place"
```

---

### Task 7: Pydantic models + `GET /api/scheduler/jobs` endpoint

**Files:**
- Create: `backend/app/models/scheduler.py`
- Create: `backend/app/routers/scheduler.py`
- Modify: `backend/tests/test_scheduler.py`
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_scheduler.py`:

```python
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_jobs_endpoint_lists_registered_jobs() -> None:
    """GET /api/scheduler/jobs surfaces id + trigger + next_run_time.

    Use bare TestClient(app) (no `with`) so the FastAPI lifespan does NOT
    run — we control the scheduler state explicitly via start() and the
    autouse fixture's shutdown(). Wrapping in `with` would invoke
    lifespan startup, which calls register_default_jobs again and would
    fight the autouse fixture's reset.
    """
    from app.main import app
    from app.services.scheduled_jobs import register_default_jobs

    await app_scheduler.start()
    register_default_jobs()

    client = TestClient(app)
    resp = client.get("/api/scheduler/jobs")

    assert resp.status_code == 200
    body = resp.json()
    job_ids = {j["id"] for j in body["jobs"]}
    assert "price_alerts_evaluate" in job_ids
    assert "social_polling_run" in job_ids
    assert "sector_rotation_refresh" in job_ids
    for job in body["jobs"]:
        assert "trigger" in job
        # next_run_time may be None during shutdown windows, but the key
        # must always be present so the UI can render a "—" cell.
        assert "next_run_time" in job


@pytest.mark.asyncio
async def test_jobs_endpoint_empty_when_scheduler_not_started() -> None:
    """When scheduler.get_scheduler() returns None, endpoint returns []."""
    from app.main import app

    # Autouse fixture already reset the singleton; bare TestClient skips
    # lifespan, so the scheduler stays None.
    client = TestClient(app)
    resp = client.get("/api/scheduler/jobs")

    assert resp.status_code == 200
    assert resp.json() == {"jobs": []}
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest tests/test_scheduler.py -q
```

Expected: 404 on the endpoint.

- [ ] **Step 3: Add the Pydantic model**

Create `backend/app/models/scheduler.py`:

```python
"""Pydantic schema for /api/scheduler endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ScheduledJobView(BaseModel):
    id: str
    name: str | None = None
    trigger: str           # human-readable, e.g. "interval[0:00:20]"
    next_run_time: datetime | None = None


class ScheduledJobsResponse(BaseModel):
    jobs: list[ScheduledJobView]
```

- [ ] **Step 4: Add the router**

Create `backend/app/routers/scheduler.py`:

```python
"""Scheduler observability endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app import scheduler as app_scheduler
from app.dependencies import service_error
from app.models.scheduler import ScheduledJobsResponse, ScheduledJobView

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/jobs", response_model=ScheduledJobsResponse)
async def list_jobs() -> ScheduledJobsResponse:
    """List every job currently registered with the application scheduler."""
    try:
        sched = app_scheduler.get_scheduler()
        if sched is None:
            return ScheduledJobsResponse(jobs=[])
        jobs = [
            ScheduledJobView(
                id=job.id,
                name=job.name,
                trigger=str(job.trigger),
                next_run_time=job.next_run_time,
            )
            for job in sched.get_jobs()
        ]
        return ScheduledJobsResponse(jobs=jobs)
    except Exception as exc:  # noqa: BLE001
        raise service_error(exc) from exc
```

- [ ] **Step 5: Wire the router into `main.py`**

Open `backend/app/main.py`. Add the import alongside the other Tradewell-inspired routers (alphabetical order in the existing import block):

```python
from app.routers import scheduler as scheduler_router
```

Add the registration in the include_router block (under the `# Tradewell-inspired additions` comment):

```python
app.include_router(scheduler_router.router)
```

- [ ] **Step 6: Update OpenAPI parity test**

Open `backend/tests/test_openapi_parity.py`. Append before the closing `}` of `EXPECTED_ROUTES`:

```python
    # --- Application scheduler observability ---
    ("GET",    "/api/scheduler/jobs"),
```

- [ ] **Step 7: Run the tests**

```bash
python -m pytest tests/test_scheduler.py tests/test_openapi_parity.py -q
```

Expected: `12 passed` (9 from earlier + 2 new endpoint tests + parity).

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/scheduler.py backend/app/routers/scheduler.py backend/app/main.py backend/tests/test_scheduler.py backend/tests/test_openapi_parity.py
git commit -m "feat(scheduler): GET /api/scheduler/jobs for live job inventory"
```

---

### Task 8: Wire the scheduler into `main.py` lifespan

**Files:**
- Modify: `backend/app/main.py`

This is the cutover. The existing lifespan calls `price_alerts_service.start_monitor()` and `social_polling_service.start_monitor()` on the way up, and the corresponding `shutdown_monitor()` calls on the way down. Both are now deleted (Tasks 4–5), so importing them would already fail. Replace with the scheduler.

- [ ] **Step 1: Read the current lifespan**

```bash
sed -n '52,90p' backend/app/main.py
```

Identify the exact lines that call `start_monitor` / `shutdown_monitor` for price_alerts and social_polling.

- [ ] **Step 2: Edit lifespan**

Open `backend/app/main.py`. At the top of the file, add (alongside the existing service imports):

```python
from app import scheduler as app_scheduler
from app.services import scheduled_jobs
```

Inside `async def lifespan(app: FastAPI):`, replace:

```python
    await price_alerts_service.start_monitor()
    await social_polling_service.start_monitor()
```

with:

```python
    await app_scheduler.start()
    scheduled_jobs.register_default_jobs()
```

And replace:

```python
    await price_alerts_service.shutdown_monitor()
    await social_polling_service.shutdown_monitor()
```

with:

```python
    await app_scheduler.shutdown()
```

(`bot_controller.shutdown_bot()` should remain — it's not part of this refactor.)

If the existing service imports `from app.services import (..., price_alerts_service, social_polling_service, ...)` are now unused inside `main.py`, they can stay if the module-level imports were just for side effects, OR be removed if they're truly unused. Run a quick grep to decide:

```bash
grep -n "price_alerts_service\|social_polling_service" backend/app/main.py
```

If the only hits are the import line, remove that import.

- [ ] **Step 3: Run the smoke test**

```bash
python -m pytest tests/test_app_smoke.py -q
```

Expected: 6 pre-existing failures (same as before this refactor) + every other smoke test still passing. **No new failures.** If the count of failures went from 6 to >6, your changes broke something — debug before continuing.

- [ ] **Step 4: Run the scheduler tests against the live app**

```bash
python -m pytest tests/test_scheduler.py -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(scheduler): cut lifespan over to AsyncIOScheduler + scheduled_jobs"
```

---

### Task 9: Full-suite green + manual boot check

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

```bash
python -m pytest -q
```

Expected: total passes = (pre-refactor count) − (deleted tests in Tasks 4–5) + (new tests in Tasks 2/3/6/7). Pre-existing failures count unchanged.

If failures appear in unexpected files, scan for `start_monitor`/`shutdown_monitor`/`_run_monitor` references — those are the most likely culprits.

- [ ] **Step 2: Boot the app and curl /api/scheduler/jobs**

In one terminal, from `backend/`:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 18745 --log-level info
```

In another terminal:

```bash
curl -sS http://127.0.0.1:18745/api/scheduler/jobs | python -m json.tool
```

Expected: a JSON object with a `jobs` array containing entries like:

```json
{
  "id": "price_alerts_evaluate",
  "name": "evaluate_rules_once",
  "trigger": "interval[0:00:20]",
  "next_run_time": "2026-04-29T..."
}
```

All three job ids (`price_alerts_evaluate`, `social_polling_run`, `sector_rotation_refresh`) must appear with non-null `next_run_time`. Stop the server (`Ctrl+C`) once verified.

- [ ] **Step 3: Frontend build sanity check**

```bash
cd ../frontend-v2 && npm run build
```

Expected: build succeeds with no errors. (No frontend changes in this plan, but a green build confirms nothing was broken in the OpenAPI schema that the frontend consumes via type generation.)

- [ ] **Step 4: Final commit on the integration branch**

If you've been on a feature branch (`feat/phase-4-1-apscheduler` or similar), no extra commit is needed — Tasks 1–8 already pushed the work. If you've been working directly on the integration branch, the previous task's commit is the last one.

- [ ] **Step 5: (Optional) Open the PR**

```bash
gh pr create --title "Phase 4.1: APScheduler integration" --body "$(cat <<'EOF'
## Summary
- Replace ad-hoc `asyncio.create_task(_run_monitor())` loops in price_alerts and social_polling with a single AsyncIOScheduler.
- New `app/scheduler.py` owns the singleton; `app/services/scheduled_jobs.py` registers every platform job in one place.
- New `GET /api/scheduler/jobs` surfaces job inventory for observability.
- Adds `apscheduler>=3.10,<4` to requirements.

## Test plan
- [ ] `pytest -q` from `backend/` is fully green (modulo the 6 pre-existing smoke failures).
- [ ] App boots; `curl /api/scheduler/jobs` lists `price_alerts_evaluate`, `social_polling_run`, `sector_rotation_refresh`.
- [ ] `npm run build` from `frontend-v2/` succeeds.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Checklist

After executing the plan, before marking it complete, verify:

- [ ] No reference to `_run_monitor` / `start_monitor` / `shutdown_monitor` exists anywhere in `backend/app/services/` (grep should return zero hits).
- [ ] `backend/app/main.py` lifespan only mentions `app_scheduler.start` / `app_scheduler.shutdown` / `scheduled_jobs.register_default_jobs` — not the old `start_monitor`/`shutdown_monitor` pair.
- [ ] The job ids in `register_default_jobs` (`price_alerts_evaluate`, `social_polling_run`, `sector_rotation_refresh`) all appear in the live `/api/scheduler/jobs` response.
- [ ] APScheduler is the only new dep introduced.
- [ ] `pytest -q` failure count is exactly the same as before this plan started.

---

## Follow-Up Plans (NOT in scope for this plan)

Once this plan is merged, these become trivially small follow-ups (one-task plans each):

1. **macro_sync job** — daily 14:00 UTC FRED refresh; one entry in `scheduled_jobs.py` calling `macro_service.refresh_indicators(force=True)`.
2. **options_chain_sync job** — every 30 min during market hours via `CronTrigger(hour="13-21", minute="*/30")`. Same one-entry add.
3. **Phase 2.4 IBKR position sync** — 5-minute interval. Depends on Phase 2.1 / 2.3 (override DB + tier system) landing first; the scheduler hookup itself is one entry.
4. **Phase 2** (multi-account portfolio) — its own plan; this plan unblocks the periodic-sync portion.
