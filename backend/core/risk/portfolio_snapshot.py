"""Broker-agnostic portfolio snapshot consumed by risk policies."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PortfolioPositionView:
    symbol: str
    qty: float
    average_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float


@dataclass
class PortfolioSnapshot:
    """A snapshot of broker state at the moment a risk check runs.

    `realized_pnl_today` is the sum of closed-trade PnL since UTC start-of-day.
    `equity` is cash + sum(market_value of open positions).
    """

    cash: float
    equity: float
    positions: dict[str, PortfolioPositionView] = field(default_factory=dict)
    realized_pnl_today: float = 0.0
    equity_high_water_mark: float = 0.0
