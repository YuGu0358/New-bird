"""Broker abstraction.

Phase 3 introduces this so the strategy engine can target either a live
broker (AlpacaBroker) or a simulated one (BacktestBroker) without code
changes inside the strategy itself.

Phase 4 will extend this with paper/live mode flags, idempotency keys,
and richer error types.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class Broker(ABC):
    """Minimal broker surface needed by Strategy B and the backtest engine."""

    @abstractmethod
    async def list_positions(self) -> list[dict[str, Any]]:
        """Return current open positions as a list of broker dicts."""

    @abstractmethod
    async def list_orders(
        self,
        *,
        status: str = "all",
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Return orders filtered by status (`all`, `open`, `closed`, ...)."""

    @abstractmethod
    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        """Submit a market order. Either `notional` (USD) or `qty` is set."""

    @abstractmethod
    async def close_position(self, symbol: str) -> dict[str, Any]:
        """Close an open position at market."""

    @abstractmethod
    async def get_account(self) -> dict[str, Any]:
        """Return account-level metrics: equity, buying_power, cash, status, etc.

        Shape (broker-agnostic minimum):
            {
                "id":         str | None,    # broker-side account id
                "status":     str,           # 'ACTIVE' | 'RESTRICTED' | ...
                "currency":   str,           # 'USD'
                "equity":     float,         # total account value
                "cash":       float,         # cash balance
                "buying_power": float,       # available buying power
            }
        Returns broker-specific keys in addition; callers should treat the
        above 6 as the contract.
        """
