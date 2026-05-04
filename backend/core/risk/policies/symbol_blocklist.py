"""Explicit deny list."""
from __future__ import annotations

from collections.abc import Iterable

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class SymbolBlocklistPolicy(RiskCheck):
    name = "symbol_blocklist"

    def __init__(self, *, symbols: Iterable[str]) -> None:
        self.symbols = {s.upper() for s in symbols if s}

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.symbol.upper() in self.symbols:
            return RiskCheckResult.deny(
                self.name,
                f"{request.symbol} is on the blocklist",
            )
        return RiskCheckResult.allow(self.name)
