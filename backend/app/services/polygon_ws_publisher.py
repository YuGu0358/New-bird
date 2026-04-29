"""Polygon WebSocket → EventBus publisher.

A long-running asyncio task that subscribes to per-symbol Polygon trade
ticks and forwards them to the application EventBus on topic
``quote:{symbol}``. Designed to be a degrade-friendly producer:

- Disabled by default (POLYGON_USE_WEBSOCKET=false). Lifespan startup
  must not break for users without Polygon credentials.
- Missing API key short-circuits to no-op rather than raising.
- WS errors restart the inner loop with exponential backoff capped at
  30 seconds. The outer task only exits on `shutdown()`.

Why a service-layer publisher instead of an APScheduler job:
APScheduler runs short-lived periodic functions; the WS connection is a
single long-lived stream. Putting it in the scheduler would fight its
"max_instances=1, coalesce=True" defaults.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import runtime_settings
from app.services import polygon_service
from app.streaming import event_bus

logger = logging.getLogger(__name__)


# Backoff schedule — grows then plateaus at 30s. The fixed sequence is
# easier to reason about than a math expression in tests.
_BACKOFF_SCHEDULE_SECONDS = (1, 2, 4, 8, 16, 30)

# Default watchlist if PINE_SEEDS_WATCHLIST is unset/empty.
WATCHLIST_DEFAULT = "SPY,QQQ,NVDA,AAPL"


_task: asyncio.Task[None] | None = None
_lock = asyncio.Lock()


def _is_enabled() -> bool:
    return runtime_settings.get_bool_setting(
        "POLYGON_USE_WEBSOCKET", default=False
    )


def _api_key_configured() -> bool:
    """Without a key the SDK can't open a session — short-circuit."""
    key = (runtime_settings.get_setting("POLYGON_API_KEY", "") or "").strip()
    return bool(key)


def _watchlist() -> list[str]:
    raw = (
        runtime_settings.get_setting("PINE_SEEDS_WATCHLIST", WATCHLIST_DEFAULT)
        or WATCHLIST_DEFAULT
    )
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


async def _publish_tick(payload: dict[str, Any]) -> None:
    """Forward one tick payload onto the bus.

    Polygon ticks come in with at minimum ``{"symbol", "price", "timestamp"}``
    after `_run_sdk_stream`'s normalization. We re-publish the dict unchanged.
    """
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        return
    try:
        await event_bus.publish(f"quote:{symbol}", payload)
    except Exception:  # noqa: BLE001 — bus errors must not kill the WS loop
        logger.exception("polygon_ws_publisher: bus publish failed")


async def _run_with_retries() -> None:
    """Inner loop: connect, run until error, back off, restart.

    Exits ONLY on cancellation. Every other exception is logged and the
    loop sleeps before reconnecting.
    """
    attempt = 0
    while True:
        try:
            symbols = _watchlist()
            if not symbols:
                logger.info(
                    "polygon_ws_publisher: empty watchlist; sleeping 60s"
                )
                await asyncio.sleep(60)
                continue
            logger.info(
                "polygon_ws_publisher: connecting (symbols=%d)", len(symbols)
            )
            await polygon_service._run_sdk_stream(  # noqa: SLF001
                symbols, _publish_tick
            )
            # If _run_sdk_stream returns cleanly, treat it as a needed
            # reconnect — the upstream library shouldn't return without
            # an error in normal operation.
            logger.warning(
                "polygon_ws_publisher: stream returned without error; reconnecting"
            )
            attempt = 0
        except asyncio.CancelledError:
            logger.info("polygon_ws_publisher: cancelled; exiting loop")
            raise
        except Exception:  # noqa: BLE001
            sleep_for = _BACKOFF_SCHEDULE_SECONDS[
                min(attempt, len(_BACKOFF_SCHEDULE_SECONDS) - 1)
            ]
            logger.exception(
                "polygon_ws_publisher: stream failed; backing off %ds", sleep_for
            )
            attempt += 1
            try:
                await asyncio.sleep(sleep_for)
            except asyncio.CancelledError:
                raise


async def start() -> None:
    """Start the publisher task if enabled. Idempotent.

    Returns immediately when the feature flag is off OR the API key is
    missing — both are normal "this user doesn't use Polygon WS"
    configurations and must not raise.
    """
    global _task
    async with _lock:
        if _task is not None and not _task.done():
            return  # already running
        if not _is_enabled():
            logger.info(
                "polygon_ws_publisher: POLYGON_USE_WEBSOCKET disabled; not starting"
            )
            return
        if not _api_key_configured():
            logger.warning(
                "polygon_ws_publisher: POLYGON_USE_WEBSOCKET=true but POLYGON_API_KEY missing; not starting"
            )
            return
        _task = asyncio.create_task(
            _run_with_retries(), name="polygon-ws-publisher"
        )


async def shutdown() -> None:
    """Cancel the publisher task and wait for cleanup. Idempotent."""
    global _task
    async with _lock:
        task = _task
        _task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass


def is_running() -> bool:
    """Test/observability helper."""
    return _task is not None and not _task.done()


def _reset_for_tests() -> None:
    """Clear any running state — production code calls shutdown() instead."""
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
    _task = None
