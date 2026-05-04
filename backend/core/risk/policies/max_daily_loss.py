"""Daily realized-loss circuit breaker.

Once realized PnL today drops below -max_loss_usd, all new buys are denied.
Sells are still allowed (so the bot can close losing positions and stop
the bleeding).
"""
from __future__ import annotations

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class MaxDailyLossPolicy(RiskCheck):
    name = "max_daily_loss"

    def __init__(self, *, max_loss_usd: float) -> None:
        if max_loss_usd <= 0:
            raise ValueError("max_loss_usd must be > 0.")
        self.max_loss_usd = float(max_loss_usd)

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.side != "buy":
            return RiskCheckResult.allow(self.name, "sell — circuit breaker bypass")

        if portfolio.realized_pnl_today <= -self.max_loss_usd:
            return RiskCheckResult.deny(
                self.name,
                f"daily loss {portfolio.realized_pnl_today:.2f} <= -{self.max_loss_usd:.2f}",
            )
        return RiskCheckResult.allow(self.name)
