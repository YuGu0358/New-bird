"""Shared types for QuantLib wrappers.

QuantLib uses its own date/calendar/option-type primitives. We translate
between simple Python types and QuantLib types here so the wrappers stay
clean and the API layer stays QuantLib-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal


OptionRight = Literal["call", "put"]
ExerciseStyle = Literal["european", "american"]


class QuantLibError(RuntimeError):
    """Wrapper around QuantLib::Error for consistent error mapping."""


@dataclass(frozen=True)
class OptionParams:
    """Inputs for European/American vanilla option pricing."""

    spot: float                # underlying price
    strike: float              # strike
    rate: float                # risk-free rate (annualized, decimal e.g. 0.05)
    dividend: float            # continuous dividend yield (decimal)
    volatility: float          # annualized volatility (decimal)
    expiry: date               # option expiry date
    valuation: date            # today / pricing date
    right: OptionRight = "call"

    def days_to_expiry(self) -> int:
        return (self.expiry - self.valuation).days


@dataclass(frozen=True)
class GreeksResult:
    delta: float
    gamma: float
    vega: float       # per 1.0 vol move (i.e. 100 vol points)
    theta: float      # per year
    rho: float        # per 1.0 rate move


@dataclass(frozen=True)
class BondParams:
    """Inputs for fixed-rate coupon bond analytics.

    `coupon_rate` is the annualized decimal coupon (e.g. 0.05 for 5%).
    `frequency` is coupons per year (1, 2, 4, 12).
    `face` is the redemption value at maturity.
    `clean_price` is the market price (per 100 face) used as reference.
    """

    settlement: date
    maturity: date
    coupon_rate: float
    frequency: int = 2
    face: float = 100.0
    clean_price: float = 100.0


@dataclass(frozen=True)
class BondAnalytics:
    yield_to_maturity: float        # annualized decimal
    macaulay_duration: float        # years
    modified_duration: float        # years
    convexity: float


@dataclass(frozen=True)
class VaRResult:
    """All values are POSITIVE numbers representing potential loss in USD."""

    var: float                       # Value at Risk
    cvar: float                      # Conditional VaR (Expected Shortfall)
    confidence: float                # e.g. 0.95
    horizon_days: int                # e.g. 1
    method: Literal["parametric", "historical"]
