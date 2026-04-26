"""End-to-end engine drive with a toy buy-the-dip strategy."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from core.backtest.engine import BacktestEngine
from core.backtest.types import Bar, BacktestConfig
from core.broker.base import Broker
from core.strategy.base import Strategy
from core.strategy.context import StrategyContext


def _make_bars(symbol: str, prices: list[float]) -> list[Bar]:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars: list[Bar] = []
    previous_close = None
    for i, close in enumerate(prices):
        ts = base + timedelta(days=i)
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=ts,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1_000_000,
                previous_close=previous_close,
            )
        )
        previous_close = close
    return bars


class _ToyDipStrategy(Strategy):
    """Buys 1000 USD on every 2% drop vs previous close, holds forever."""

    name = "toy_dip_v1"
    description = "Buy 1000 USD when price drops 2% below previous close."

    @classmethod
    def parameters_schema(cls):
        from app.models import StrategyExecutionParameters
        return StrategyExecutionParameters

    def __init__(self, parameters, *, broker: Broker | None = None) -> None:
        super().__init__(parameters)
        self._broker = broker

    def universe(self) -> list[str]:
        return list(self.parameters.universe_symbols)

    async def on_start(self, ctx: StrategyContext) -> None:
        return None

    async def on_periodic_sync(self, ctx, now: datetime) -> None:
        return None

    async def on_tick(self, ctx, *, symbol: str, price: float, previous_close: float, timestamp=None):
        if previous_close <= 0:
            return
        drop = (price - previous_close) / previous_close
        if drop <= -0.02 and self._broker is not None:
            await self._broker.submit_order(symbol=symbol, side="buy", notional=1000.0)


@pytest.mark.asyncio
async def test_engine_runs_toy_strategy_to_completion() -> None:
    from app.models import StrategyExecutionParameters

    bars_aapl = _make_bars(
        "AAPL",
        [100.0, 100.0, 95.0, 96.0, 97.0, 98.0, 100.0, 102.0],
    )
    config = BacktestConfig(
        strategy_name="toy_dip_v1",
        parameters={"universe_symbols": ["AAPL"]},
        universe=["AAPL"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 9),
        initial_cash=10_000.0,
    )

    parameters = StrategyExecutionParameters(
        universe_symbols=["AAPL"],
        entry_drop_percent=2.0,
        add_on_drop_percent=2.0,
        initial_buy_notional=1000.0,
        add_on_buy_notional=100.0,
        max_daily_entries=1,
        max_add_ons=0,
        take_profit_target=80.0,
        stop_loss_percent=12.0,
        max_hold_days=30,
    )

    def _strategy_factory(broker: Broker) -> Strategy:
        return _ToyDipStrategy(parameters, broker=broker)

    engine = BacktestEngine(config=config, strategy_factory=_strategy_factory)
    result = await engine.run({"AAPL": bars_aapl})

    # The strategy buys on the 5% drop on day 3 (95 vs 100). Cash should be
    # 10000 - 1000 = 9000. One trade recorded.
    assert len(result.trades) >= 1
    assert result.trades[0].side == "buy"
    assert round(result.final_cash, 2) <= 9_000.0
    assert len(result.equity_curve) == len(bars_aapl)
    assert result.metrics["total_return"] != 0.0 or result.metrics["max_drawdown"] != 0.0
