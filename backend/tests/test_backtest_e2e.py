"""End-to-end: Strategy B backtested over mocked yfinance bars."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

import strategies  # noqa: F401  -- decorators

from app.models import StrategyExecutionParameters

from core.backtest import BacktestConfig, BacktestEngine, Bar
from core.broker.base import Broker
from core.strategy.registry import default_registry


def _synthetic_bars(symbol: str, days: int = 60) -> list[Bar]:
    """Build a synthetic price path that triggers Strategy B's entry rule."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars: list[Bar] = []
    previous_close = None
    prices: list[float] = []
    cur = 100.0
    for i in range(days):
        if i == 3:
            cur = cur * 0.97  # 3% drop triggers entry
        elif i in (10, 15, 20, 30):
            cur *= 1.005
        else:
            cur *= 1.001
        prices.append(round(cur, 4))
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


@pytest.mark.asyncio
async def test_strategy_b_backtest_runs_and_reports_metrics() -> None:
    parameters = StrategyExecutionParameters(
        universe_symbols=["AAPL"],
        entry_drop_percent=2.0,
        add_on_drop_percent=2.0,
        initial_buy_notional=1000.0,
        add_on_buy_notional=100.0,
        max_daily_entries=1,
        max_add_ons=2,
        take_profit_target=80.0,
        stop_loss_percent=12.0,
        max_hold_days=30,
    )

    bars = {"AAPL": _synthetic_bars("AAPL", days=60)}
    config = BacktestConfig(
        strategy_name="strategy_b_v1",
        parameters=parameters.model_dump(),
        universe=["AAPL"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 3, 1),
        initial_cash=10_000.0,
    )

    strategy_cls = default_registry.get("strategy_b_v1")

    def _factory(broker: Broker):
        return strategy_cls(parameters, broker=broker)

    engine = BacktestEngine(config=config, strategy_factory=_factory)
    result = await engine.run(bars)

    assert len(result.equity_curve) == 60
    assert {"total_return", "sharpe", "max_drawdown"} <= set(result.metrics.keys())
    assert isinstance(result.final_equity, float)
