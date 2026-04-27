"""Value types passed across the risk layer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class OrderRequest:
    """A proposed order, presented to risk policies for approval.

    `notional` (USD) and `qty` are mutually exclusive. `current_price` is the
    broker's last-known price for the symbol, used by policies to convert
    qty-based orders into notional terms.
    """

    symbol: str
    side: str  # "buy" | "sell"
    notional: Optional[float] = None
    qty: Optional[float] = None
    current_price: Optional[float] = None
    requested_at: Optional[datetime] = None

    def estimated_notional(self) -> float:
        """Return the absolute notional of this order in USD, best effort."""
        if self.notional is not None:
            return abs(self.notional)
        if self.qty is not None and self.current_price is not None:
            return abs(self.qty * self.current_price)
        return 0.0


@dataclass(frozen=True)
class RiskCheckResult:
    """Output of a single RiskCheck.evaluate call."""

    allowed: bool
    policy_name: str
    reason: str = ""

    @classmethod
    def allow(cls, policy_name: str, reason: str = "") -> "RiskCheckResult":
        return cls(allowed=True, policy_name=policy_name, reason=reason)

    @classmethod
    def deny(cls, policy_name: str, reason: str) -> "RiskCheckResult":
        return cls(allowed=False, policy_name=policy_name, reason=reason)
