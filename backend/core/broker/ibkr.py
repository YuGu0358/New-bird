"""IBKRBroker — delegates each Broker method to app.services.ibkr_service."""
from __future__ import annotations

from typing import Any, Optional

from app.services import ibkr_service

from core.broker.base import Broker


class IBKRBroker(Broker):
    """Adapter: existing ibkr_service module behind the Broker interface.

    Holds no state. All methods forward to the module-level coroutines, so
    monkeypatches against ``app.services.ibkr_service`` continue to work in
    tests that target the legacy path. Mirrors :class:`AlpacaBroker`.
    """

    async def get_account(self) -> dict[str, Any]:
        return await ibkr_service.get_account()

    async def list_positions(self) -> list[dict[str, Any]]:
        return await ibkr_service.list_positions()

    async def list_orders(
        self,
        *,
        status: str = "all",
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"status": status}
        if limit is not None:
            kwargs["limit"] = limit
        return await ibkr_service.list_orders(**kwargs)

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        return await ibkr_service.submit_order(
            symbol=symbol,
            side=side,
            notional=notional,
            qty=qty,
        )

    async def close_position(self, symbol: str) -> dict[str, Any]:
        return await ibkr_service.close_position(symbol)
