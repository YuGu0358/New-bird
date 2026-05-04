from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

import strategies  # noqa: F401  -- triggers @register_strategy decorators

from app.database import init_database
from app.services import alpaca_service as _alpaca_service
from app.services import polygon_service, strategy_profiles_service

from core.risk.portfolio_snapshot import PortfolioPositionView, PortfolioSnapshot
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


async def _live_portfolio_snapshot() -> PortfolioSnapshot:
    try:
        account = await _alpaca_service.get_account()
    except Exception:
        account = {}
    try:
        positions = await _alpaca_service.list_positions()
    except Exception:
        positions = []

    pos_views: dict[str, PortfolioPositionView] = {}
    for p in positions:
        symbol = str(p.get("symbol", "")).upper()
        if not symbol:
            continue
        try:
            qty = float(p.get("qty", 0) or 0)
            entry = float(p.get("avg_entry_price", p.get("entry_price", 0)) or 0)
            current = float(p.get("current_price", entry) or entry)
            mv = float(p.get("market_value", qty * current) or qty * current)
            upl = float(p.get("unrealized_pl", (current - entry) * qty) or 0)
        except (TypeError, ValueError):
            continue
        pos_views[symbol] = PortfolioPositionView(
            symbol=symbol,
            qty=qty,
            average_entry_price=entry,
            current_price=current,
            market_value=mv,
            unrealized_pl=upl,
        )

    cash = float(account.get("cash", 0) or 0)
    equity = float(account.get("equity", cash) or cash)

    realized_today = 0.0
    try:
        from app.database import AsyncSessionLocal
        from app.services import pnl_service

        async with AsyncSessionLocal() as session:
            realized_today = await pnl_service.realized_pnl_today(session)
    except Exception:
        # PnL lookup failure must not block trading - fall back to 0.
        realized_today = 0.0

    return PortfolioSnapshot(
        cash=cash,
        equity=equity,
        positions=pos_views,
        realized_pnl_today=realized_today,
    )


async def _build_active_strategy():
    """Resolve the active strategy class + parameters from the profiles service."""
    from app.database import AsyncSessionLocal
    from app.services import risk_service

    from core.broker import AlpacaBroker
    from core.risk import RiskGuard

    strategy_display_name, parameters = await strategy_profiles_service.get_active_strategy_execution_profile()
    strategy_cls = default_registry.get(DEFAULT_STRATEGY_NAME)

    # Load risk config from DB and wrap broker.
    base_broker = AlpacaBroker()
    async with AsyncSessionLocal() as session:
        risk_view = await risk_service.get_config_view(session)
    if risk_view.get("enabled"):
        policies = risk_service.build_policies_from_config(risk_view)
        if policies:
            base_broker = RiskGuard(base_broker, policies=policies, snapshot_provider=_live_portfolio_snapshot)

    strategy = strategy_cls(parameters, broker=base_broker)
    logger.info(
        "Loaded strategy %s (display=%r, risk-policies=%d) with universe size %d",
        DEFAULT_STRATEGY_NAME,
        strategy_display_name,
        len(risk_service.build_policies_from_config(risk_view)) if risk_view.get("enabled") else 0,
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
