"""Value types passed around the backtest pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass(frozen=True)
class Bar:
    """Daily OHLCV bar for a single symbol."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    previous_close: Optional[float] = None


@dataclass
class BacktestConfig:
    """Inputs for a single backtest run."""

    strategy_name: str
    parameters: dict
    universe: list[str]
    start_date: date
    end_date: date
    initial_cash: float = 100_000.0


@dataclass
class BacktestTradeRecord:
    """A single fill recorded during the backtest."""

    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    price: float
    notional: float
    timestamp: datetime
    reason: str = ""


@dataclass
class BacktestResult:
    """Outcome of a backtest run before persistence."""

    config: BacktestConfig
    started_at: datetime
    finished_at: datetime
    final_cash: float
    final_equity: float
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    trades: list[BacktestTradeRecord] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
