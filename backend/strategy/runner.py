from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

import strategies  # noqa: F401  -- triggers @register_strategy decorators

from app.database import init_database
from app.services import polygon_service, strategy_profiles_service

from core.strategy.context import StrategyContext
from core.strategy.registry import default_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BROKER_SYNC_INTERVAL_SECONDS = 10
QUOTE_POLL_INTERVAL_SECONDS = 5

# Until strategy_profiles supports per-profile strategy_type, treat every
# active profile as Strategy B. Phase 4+ will add that field.
DEFAULT_STRATEGY_NAME = "strategy_b_v1"


async def _build_active_strategy():
    """Resolve the active strategy class + parameters from the profiles service."""
    strategy_display_name, parameters = await strategy_profiles_service.get_active_strategy_execution_profile()
    strategy_cls = default_registry.get(DEFAULT_STRATEGY_NAME)
    strategy = strategy_cls(parameters)
    logger.info(
        "Loaded strategy %s (display=%r) with universe size %d",
        DEFAULT_STRATEGY_NAME,
        strategy_display_name,
        len(strategy.universe()),
    )
    return strategy


async def main() -> None:
    await init_database()

    strategy = await _build_active_strategy()
    ctx = StrategyContext(parameters=strategy.parameters, logger=logger)

    await strategy.on_start(ctx)

    previous_close_cache: dict[str, tuple[date, float]] = {}
    last_broker_sync_at = datetime.now(timezone.utc)

    async def handle_msg(message: dict[str, object]) -> None:
        nonlocal last_broker_sync_at
        symbol = str(message.get("symbol", "")).upper()
        if not symbol:
            return

        price = float(message.get("price", 0.0) or 0.0)
        if price <= 0:
            return

        now = datetime.now(timezone.utc)
        if (now - last_broker_sync_at).total_seconds() >= BROKER_SYNC_INTERVAL_SECONDS:
            try:
                await strategy.on_periodic_sync(ctx, now)
                last_broker_sync_at = now
            except Exception:
                logger.exception("Strategy periodic sync failed")

        previous_close = message.get("previous_close")
        if previous_close is None:
            today = now.date()
            cached_item = previous_close_cache.get(symbol)
            if cached_item is not None and cached_item[0] == today:
                previous_close = cached_item[1]

        if previous_close is None:
            try:
                previous_close = await polygon_service.get_previous_close(symbol)
                previous_close_cache[symbol] = (
                    now.date(),
                    float(previous_close),
                )
            except Exception as exc:
                logger.warning("Skipping %s because previous close could not be loaded: %s", symbol, exc)
                return

        try:
            await strategy.on_tick(
                ctx,
                symbol=symbol,
                price=price,
                previous_close=float(previous_close),
                timestamp=message.get("timestamp"),
            )
        except Exception:
            logger.exception("Strategy evaluation failed for %s", symbol)

    try:
        while True:
            try:
                await polygon_service.stream_quotes(
                    strategy.universe(),
                    handle_msg,
                    poll_seconds=QUOTE_POLL_INTERVAL_SECONDS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Polygon quote stream stopped unexpectedly. Restarting in 5 seconds.")
                await asyncio.sleep(5)
    finally:
        try:
            await strategy.on_stop(ctx)
        except Exception:
            logger.exception("Strategy on_stop hook raised")


if __name__ == "__main__":
    asyncio.run(main())
