"""Concurrent open-position count cap. Adding to an existing position is allowed."""
from __future__ import annotations

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class MaxOpenPositionsPolicy(RiskCheck):
    name = "max_open_positions"

    def __init__(self, *, max_positions: int) -> None:
        self.max_positions = int(max_positions)

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.side != "buy":
            return RiskCheckResult.allow(self.name, "sell — not capped")

        already_open = len(portfolio.positions)
        if request.symbol in portfolio.positions:
            return RiskCheckResult.allow(self.name, "add-on to existing position")
        if already_open >= self.max_positions:
            return RiskCheckResult.deny(
                self.name,
                f"open positions {already_open} >= cap {self.max_positions}",
            )
        return RiskCheckResult.allow(self.name)
