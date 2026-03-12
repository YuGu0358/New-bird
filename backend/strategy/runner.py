from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from app.database import init_database
from app.services import polygon_service, strategy_profiles_service
from strategy.strategy_b import StrategyBEngine, StrategyExecutionConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BROKER_SYNC_INTERVAL_SECONDS = 10
QUOTE_POLL_INTERVAL_SECONDS = 5


async def _load_execution_config() -> StrategyExecutionConfig:
    strategy_name, parameters = await strategy_profiles_service.get_active_strategy_execution_profile()
    return StrategyExecutionConfig(
        universe=parameters.universe_symbols,
        entry_drop_threshold=parameters.entry_drop_percent / 100,
        add_on_drop_threshold=parameters.add_on_drop_percent / 100,
        initial_buy_notional=parameters.initial_buy_notional,
        add_on_buy_notional=parameters.add_on_buy_notional,
        max_daily_entries=parameters.max_daily_entries,
        max_add_ons=parameters.max_add_ons,
        take_profit_target=parameters.take_profit_target,
        stop_loss_threshold=parameters.stop_loss_percent / 100,
        max_hold_days=parameters.max_hold_days,
        strategy_name=strategy_name,
    )


async def main() -> None:
    await init_database()

    engine = StrategyBEngine(await _load_execution_config())
    await engine.sync_from_broker()
    await engine.evaluate_broker_positions()

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
                await engine.sync_from_broker()
                await engine.evaluate_broker_positions(now)
                last_broker_sync_at = now
            except Exception:
                logger.exception("Broker state sync failed")

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
            await engine.process_tick(
                symbol=symbol,
                current_price=price,
                previous_close=float(previous_close),
                timestamp=message.get("timestamp"),
            )
        except Exception:
            logger.exception("Strategy evaluation failed for %s", symbol)

    while True:
        try:
            await polygon_service.stream_quotes(
                engine.config.universe,
                handle_msg,
                poll_seconds=QUOTE_POLL_INTERVAL_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Polygon quote stream stopped unexpectedly. Restarting in 5 seconds.")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
