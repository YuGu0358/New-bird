"""Sum of all open notionals as percentage of equity."""
from __future__ import annotations

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class MaxTotalExposurePolicy(RiskCheck):
    name = "max_total_exposure"

    def __init__(self, *, max_exposure_pct: float) -> None:
        if not 0 < max_exposure_pct <= 1.0:
            raise ValueError("max_exposure_pct must be in (0, 1].")
        self.max_exposure_pct = float(max_exposure_pct)

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.side != "buy":
            return RiskCheckResult.allow(self.name, "sell — not capped")
        if portfolio.equity <= 0:
            return RiskCheckResult.deny(self.name, "non-positive equity")

        current_exposure = sum(pos.market_value for pos in portfolio.positions.values())
        proposed_exposure = current_exposure + request.estimated_notional()
        ratio = proposed_exposure / portfolio.equity
        if ratio > self.max_exposure_pct:
            return RiskCheckResult.deny(
                self.name,
                f"total exposure ratio {ratio:.3f} > cap {self.max_exposure_pct:.3f}",
            )
        return RiskCheckResult.allow(self.name)
