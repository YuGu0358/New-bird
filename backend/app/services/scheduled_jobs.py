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

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import runtime_settings, scheduler as app_scheduler
from app.services import (
    macro_service,
    options_chain_service,
    position_sync_service,
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

OPTIONS_CHAIN_SYNC_INTERVAL_SECONDS = 30 * 60
# US equity regular session: 13:30–20:00 UTC (09:30–16:00 ET).
# Cron uses UTC since AsyncIOScheduler is UTC-by-default.

POSITION_SYNC_INTERVAL_SECONDS = 5 * 60


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


async def _macro_sync() -> None:
    """Force-refresh the macro indicator dashboard cache.

    FRED publishes most series on a daily cadence in the US morning;
    14:00 UTC (10am ET) is after the bulk of releases.
    """
    try:
        await macro_service.get_dashboard(force=True)
    except Exception:  # noqa: BLE001
        logger.exception("macro_sync job failed")


async def _options_chain_sync() -> None:
    """Force-refresh the options chain cache for the watchlist.

    Reads PINE_SEEDS_WATCHLIST (comma-separated) via the shared
    `watchlist.get_watchlist()` helper so the canonical default lives in
    runtime_settings only. Per-ticker failures are logged at DEBUG and
    don't block the rest of the batch.
    """
    from app.services.watchlist import get_watchlist

    symbols = get_watchlist()
    for symbol in symbols:
        try:
            await options_chain_service.get_gex_summary(symbol, force=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "options_chain_sync skipped %s: %s", symbol, exc
            )


async def _position_sync() -> None:
    """5-min IBKR position snapshot pass.

    `position_sync_service.snapshot_once` opens its own session and
    swallows per-pass errors; we just call it. The number of rows
    written is logged at debug for ops visibility.
    """
    try:
        written = await position_sync_service.snapshot_once()
        if written:
            logger.debug("position_sync: wrote %d snapshot rows", written)
    except Exception:  # noqa: BLE001
        logger.exception("position_sync job failed")


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
    app_scheduler.register_job(
        "macro_sync",
        _macro_sync,
        # Daily at 14:00 UTC (10am ET) — after the typical FRED
        # morning release window.
        CronTrigger(hour=14, minute=0),
    )
    app_scheduler.register_job(
        "options_chain_sync",
        _options_chain_sync,
        # Every 30 minutes during the US regular session window.
        # day_of_week='mon-fri' skips weekends. Cron in UTC.
        CronTrigger(
            day_of_week="mon-fri",
            hour="13-19",
            minute="*/30",
        ),
    )
    app_scheduler.register_job(
        "position_sync",
        _position_sync,
        IntervalTrigger(seconds=POSITION_SYNC_INTERVAL_SECONDS),
    )
