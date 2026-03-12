from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from strategy import runner

_runner_task: asyncio.Task[None] | None = None
_started_at: datetime | None = None
_last_error: str | None = None
_lock = asyncio.Lock()


def _is_running() -> bool:
    return _runner_task is not None and not _runner_task.done()


def _on_task_done(task: asyncio.Task[None]) -> None:
    global _runner_task, _started_at, _last_error

    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # pragma: no cover - defensive state capture
        _last_error = str(exc)
    finally:
        _runner_task = None
        _started_at = None


async def get_status() -> dict[str, Any]:
    running = _is_running()
    uptime_seconds = None

    if running and _started_at is not None:
        uptime_seconds = int((datetime.now(timezone.utc) - _started_at).total_seconds())

    return {
        "is_running": running,
        "started_at": _started_at,
        "uptime_seconds": uptime_seconds,
        "last_error": _last_error,
    }


async def start_bot() -> dict[str, Any]:
    global _runner_task, _started_at, _last_error

    async with _lock:
        if _is_running():
            return await get_status()

        _last_error = None
        _started_at = datetime.now(timezone.utc)
        _runner_task = asyncio.create_task(runner.main(), name="strategy-runner")
        _runner_task.add_done_callback(_on_task_done)

    await asyncio.sleep(0)
    return await get_status()


async def stop_bot() -> dict[str, Any]:
    async with _lock:
        task = _runner_task
        if task is None or task.done():
            return await get_status()
        task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    return await get_status()


async def shutdown_bot() -> None:
    await stop_bot()
