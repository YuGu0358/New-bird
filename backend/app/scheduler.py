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
