"""RiskGuard — wraps a Broker with pre-trade policy checks."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Awaitable, Callable, Optional

from core.broker.base import Broker
from core.risk.base import RiskCheck
from core.risk.errors import RiskViolationError
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult

SnapshotProvider = Callable[[], PortfolioSnapshot] | Callable[[], Awaitable[PortfolioSnapshot]]


class RiskGuard(Broker):
    """Decorator: intercept submit_order, run all policies, log violations.

    `snapshot_provider` returns the current PortfolioSnapshot. It can be sync
    or async — the guard awaits if needed. `close_position` and the read-only
    methods (list_positions, list_orders) are NOT gated.
    """

    def __init__(
        self,
        inner: Broker,
        *,
        policies: Sequence[RiskCheck],
        snapshot_provider: SnapshotProvider,
        logger: logging.Logger | None = None,
    ) -> None:
        self._inner = inner
        self._policies = list(policies)
        self._snapshot_provider = snapshot_provider
        self._logger = logger or logging.getLogger("risk.guard")
        self.violations: list[RiskCheckResult] = []

    async def _resolve_snapshot(self) -> PortfolioSnapshot:
        result = self._snapshot_provider()
        if hasattr(result, "__await__"):
            return await result  # type: ignore[no-any-return]
        return result  # type: ignore[return-value]

    async def list_positions(self) -> list[dict[str, Any]]:
        return await self._inner.list_positions()

    async def list_orders(self, *, status: str = "all", limit: Optional[int] = None) -> list[dict[str, Any]]:
        return await self._inner.list_orders(status=status, limit=limit)

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        snapshot = await self._resolve_snapshot()
        request = OrderRequest(
            symbol=symbol,
            side=side,
            notional=notional,
            qty=qty,
            current_price=(snapshot.positions[symbol].current_price if symbol in snapshot.positions else None),
        )
        for policy in self._policies:
            result = await policy.evaluate(request, snapshot)
            if not result.allowed:
                self.violations.append(result)
                self._logger.warning(
                    "RiskGuard rejected %s %s: %s — %s",
                    side,
                    symbol,
                    result.policy_name,
                    result.reason,
                )
                raise RiskViolationError(result)
        return await self._inner.submit_order(symbol=symbol, side=side, notional=notional, qty=qty)

    async def close_position(self, symbol: str) -> dict[str, Any]:
        # Closes are never gated — they are how the system de-risks.
        return await self._inner.close_position(symbol)
