"""AlpacaBroker — delegates each Broker method to app.services.alpaca_service."""
from __future__ import annotations

from typing import Any, Optional

from app.services import alpaca_service

from core.broker.base import Broker


class AlpacaBroker(Broker):
    """Adapter: existing alpaca_service module behind the Broker interface.

    Holds no state. All methods forward to the module-level functions, so
    monkeypatches against `app.services.alpaca_service` continue to work
    in tests that target the legacy path.
    """

    async def list_positions(self) -> list[dict[str, Any]]:
        return await alpaca_service.list_positions()

    async def list_orders(
        self,
        *,
        status: str = "all",
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"status": status}
        if limit is not None:
            kwargs["limit"] = limit
        return await alpaca_service.list_orders(**kwargs)

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"symbol": symbol, "side": side}
        if notional is not None:
            kwargs["notional"] = notional
        if qty is not None:
            kwargs["qty"] = qty
        return await alpaca_service.submit_order(**kwargs)

    async def close_position(self, symbol: str) -> dict[str, Any]:
        return await alpaca_service.close_position(symbol)
