"""Backtest engine package — public API."""
from __future__ import annotations

from core.backtest.broker import BacktestBroker
from core.backtest.engine import BacktestEngine, StrategyFactory
from core.backtest.loader import load_daily_bars
from core.backtest.metrics import (
    cagr,
    calmar_ratio,
    compute_metrics,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    total_return,
    win_rate,
)
from core.backtest.portfolio import BacktestPortfolio
from core.backtest.types import (
    Bar,
    BacktestConfig,
    BacktestResult,
    BacktestTradeRecord,
)

__all__ = [
    "Bar",
    "BacktestBroker",
    "BacktestConfig",
    "BacktestEngine",
    "BacktestPortfolio",
    "BacktestResult",
    "BacktestTradeRecord",
    "StrategyFactory",
    "cagr",
    "calmar_ratio",
    "compute_metrics",
    "load_daily_bars",
    "max_drawdown",
    "profit_factor",
    "sharpe_ratio",
    "sortino_ratio",
    "total_return",
    "win_rate",
]
