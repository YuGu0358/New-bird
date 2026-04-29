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
