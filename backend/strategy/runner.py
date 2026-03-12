from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

from app.database import init_database
from app.services import polygon_service
from strategy.strategy_b import StrategyBEngine, UNIVERSE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BROKER_SYNC_INTERVAL_SECONDS = 10
QUOTE_POLL_INTERVAL_SECONDS = 5


async def main() -> None:
    await init_database()

    engine = StrategyBEngine()
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
                UNIVERSE,
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
