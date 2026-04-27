"""Risk layer exceptions."""
from __future__ import annotations

from core.risk.types import RiskCheckResult


class RiskViolationError(RuntimeError):
    """Raised when a risk policy denies an order.

    Carries the failing RiskCheckResult so callers (broker wrappers, audit
    code, API error handlers) can introspect the rejection reason.
    """

    def __init__(self, result: RiskCheckResult) -> None:
        super().__init__(f"{result.policy_name}: {result.reason}")
        self.result = result
