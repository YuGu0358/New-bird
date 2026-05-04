"""Per-symbol notional cap."""
from __future__ import annotations

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class MaxPositionSizePolicy(RiskCheck):
    name = "max_position_size"

    def __init__(self, *, max_notional_per_symbol: float) -> None:
        self.max_notional_per_symbol = float(max_notional_per_symbol)

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.side != "buy":
            return RiskCheckResult.allow(self.name, "sell — not capped")

        existing = portfolio.positions.get(request.symbol)
        existing_notional = existing.market_value if existing else 0.0
        proposed_notional = request.estimated_notional()
        combined = existing_notional + proposed_notional

        if combined > self.max_notional_per_symbol:
            return RiskCheckResult.deny(
                self.name,
                f"{request.symbol} exposure {combined:.2f} > cap {self.max_notional_per_symbol:.2f}",
            )
        return RiskCheckResult.allow(self.name)
