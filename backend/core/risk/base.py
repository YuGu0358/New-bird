"""RiskCheck ABC — the interface every concrete risk policy implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class RiskCheck(ABC):
    """Abstract base for pre-trade risk policies.

    Stateless evaluators: given a proposed order and the current portfolio
    snapshot, return RiskCheckResult.allow or RiskCheckResult.deny.
    """

    name: str = ""

    @abstractmethod
    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        """Return RiskCheckResult; never raise on rule violation."""
