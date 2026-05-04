"""BacktestPortfolio — in-memory simulator for cash, positions, fills."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.backtest.types import BacktestTradeRecord


@dataclass
class _PositionState:
    symbol: str
    qty: float
    average_entry_price: float
    total_cost: float
    opened_at: datetime


class InsufficientCashError(RuntimeError):
    """Raised when a fill would push cash below zero."""


class PositionNotOpenError(RuntimeError):
    """Raised when closing a symbol that has no open position."""


@dataclass
class BacktestPortfolio:
    initial_cash: float
    cash: float = field(init=False)
    positions: dict[str, _PositionState] = field(default_factory=dict)
    trades: list[BacktestTradeRecord] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = float(self.initial_cash)

    def equity(self, *, prices: dict[str, float]) -> float:
        total = self.cash
        for symbol, pos in self.positions.items():
            mark = prices.get(symbol, pos.average_entry_price)
            total += pos.qty * mark
        return total

    def record_equity_snapshot(self, *, timestamp: datetime, prices: dict[str, float]) -> None:
        self.equity_curve.append((timestamp, self.equity(prices=prices)))

    def fill_buy(
        self,
        *,
        symbol: str,
        price: float,
        timestamp: datetime,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
        reason: str = "",
    ) -> BacktestTradeRecord:
        if (notional is None) == (qty is None):
            raise ValueError("Exactly one of notional or qty must be provided.")
        if price <= 0:
            raise ValueError("price must be > 0")

        if qty is None:
            assert notional is not None
            qty = notional / price
        cost = qty * price
        if cost > self.cash + 1e-9:
            raise InsufficientCashError(
                f"buy {symbol} cost {cost:.2f} exceeds cash {self.cash:.2f}"
            )

        existing = self.positions.get(symbol)
        if existing is None:
            self.positions[symbol] = _PositionState(
                symbol=symbol,
                qty=qty,
                average_entry_price=price,
                total_cost=cost,
                opened_at=timestamp,
            )
        else:
            new_qty = existing.qty + qty
            new_total_cost = existing.total_cost + cost
            existing.qty = new_qty
            existing.total_cost = new_total_cost
            existing.average_entry_price = new_total_cost / new_qty if new_qty > 0 else 0.0

        self.cash -= cost
        trade = BacktestTradeRecord(
            symbol=symbol,
            side="buy",
            qty=qty,
            price=price,
            notional=cost,
            timestamp=timestamp,
            reason=reason,
        )
        self.trades.append(trade)
        return trade

    def fill_close(
        self,
        *,
        symbol: str,
        price: float,
        timestamp: datetime,
        reason: str = "",
    ) -> BacktestTradeRecord:
        if price <= 0:
            raise ValueError("price must be > 0")
        position = self.positions.get(symbol)
        if position is None:
            raise PositionNotOpenError(f"No open position for {symbol}")

        proceeds = position.qty * price
        trade = BacktestTradeRecord(
            symbol=symbol,
            side="sell",
            qty=position.qty,
            price=price,
            notional=proceeds,
            timestamp=timestamp,
            reason=reason,
        )
        self.cash += proceeds
        self.trades.append(trade)
        del self.positions[symbol]
        return trade
