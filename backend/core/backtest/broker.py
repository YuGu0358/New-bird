"""BacktestBroker — Broker implementation backed by a BacktestPortfolio.

Strategy B receives this in lieu of AlpacaBroker during backtest. The broker
needs a `prices` callable that returns the current bar's price per symbol so
fills happen at the appropriate close.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.backtest.portfolio import BacktestPortfolio
from core.broker.base import Broker


class BacktestBroker(Broker):
    """Routes Strategy B's broker calls to a BacktestPortfolio.

    `current_price_provider` returns the close-of-bar price for a symbol at
    the simulated "now". `current_time_provider` returns the simulated
    timestamp. The engine sets these before each strategy callback.
    """

    def __init__(
        self,
        portfolio: BacktestPortfolio,
        *,
        current_price_provider: Callable[[str], float],
        current_time_provider: Callable[[], datetime],
    ) -> None:
        self.portfolio = portfolio
        self._current_price = current_price_provider
        self._current_time = current_time_provider
        self._next_order_id = 1

    def _new_order_id(self) -> str:
        oid = f"backtest-{self._next_order_id}"
        self._next_order_id += 1
        return oid

    async def list_positions(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol, pos in self.portfolio.positions.items():
            current_price = self._current_price(symbol)
            unrealized = (current_price - pos.average_entry_price) * pos.qty
            rows.append(
                {
                    "symbol": symbol,
                    "qty": str(pos.qty),
                    "avg_entry_price": str(pos.average_entry_price),
                    "current_price": str(current_price),
                    "market_value": str(pos.qty * current_price),
                    "unrealized_pl": str(unrealized),
                }
            )
        return rows

    async def list_orders(
        self,
        *,
        status: str = "all",
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        # Backtest fills resolve synchronously inside submit_order; nothing
        # ever sits "open". Strategy B treats an empty open list as healthy.
        return []

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        price = self._current_price(symbol)
        timestamp = self._current_time() or datetime.now(timezone.utc)

        if side == "buy":
            self.portfolio.fill_buy(
                symbol=symbol,
                price=price,
                timestamp=timestamp,
                notional=notional,
                qty=qty,
            )
        elif side == "sell":
            self.portfolio.fill_close(
                symbol=symbol,
                price=price,
                timestamp=timestamp,
            )
        else:
            raise ValueError(f"Unsupported side: {side!r}")

        return {
            "id": self._new_order_id(),
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "notional": notional,
            "filled_avg_price": price,
            "status": "filled",
        }

    async def close_position(self, symbol: str) -> dict[str, Any]:
        price = self._current_price(symbol)
        timestamp = self._current_time() or datetime.now(timezone.utc)
        self.portfolio.fill_close(
            symbol=symbol,
            price=price,
            timestamp=timestamp,
            reason="strategy_close",
        )
        return {
            "id": self._new_order_id(),
            "symbol": symbol,
            "status": "filled",
        }
