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
