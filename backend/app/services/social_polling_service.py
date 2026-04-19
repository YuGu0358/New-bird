from __future__ import annotations

import asyncio
import logging

from app.database import AsyncSessionLocal
from app.services import social_signal_service

logger = logging.getLogger(__name__)

_monitor_task: asyncio.Task[None] | None = None
_monitor_lock = asyncio.Lock()


def _is_running() -> bool:
    return _monitor_task is not None and not _monitor_task.done()


def _poll_interval_seconds() -> int:
    return social_signal_service.DEFAULT_SOCIAL_POLL_INTERVAL_MINUTES * 60


async def evaluate_once(*, execute: bool = False, force_refresh: bool = False) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        return await social_signal_service.run_social_monitor(
            session,
            include_watchlist=True,
            include_positions=True,
            include_candidates=True,
            execute=execute,
            force_refresh=force_refresh,
        )


async def _run_monitor() -> None:
    while True:
        try:
            if social_signal_service.is_market_session_open():
                await evaluate_once(
                    execute=False,
                    force_refresh=False,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Social polling monitor failed unexpectedly")

        await asyncio.sleep(_poll_interval_seconds())


def _on_monitor_done(task: asyncio.Task[None]) -> None:
    global _monitor_task
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Social polling monitor stopped with an unexpected error")
    finally:
        _monitor_task = None


async def start_monitor() -> None:
    global _monitor_task

    async with _monitor_lock:
        if _is_running():
            return
        _monitor_task = asyncio.create_task(_run_monitor(), name="social-polling-monitor")
        _monitor_task.add_done_callback(_on_monitor_done)


async def shutdown_monitor() -> None:
    async with _monitor_lock:
        task = _monitor_task
        if task is None or task.done():
            return
        task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass
