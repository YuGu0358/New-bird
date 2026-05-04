"""QuantLib wrappers — option pricing, bond analytics, risk metrics."""
from __future__ import annotations

from core.quantlib.base import (
    BondAnalytics,
    BondParams,
    ExerciseStyle,
    GreeksResult,
    OptionParams,
    OptionRight,
    QuantLibError,
    VaRResult,
)
from core.quantlib.bonds import bond_risk_metrics, bond_yield_to_maturity
from core.quantlib.options import (
    greeks_european_bs,
    price_american_binomial,
    price_european_bs,
)
from core.quantlib.risk import historical_var, parametric_var

__all__ = [
    "BondAnalytics",
    "BondParams",
    "ExerciseStyle",
    "GreeksResult",
    "OptionParams",
    "OptionRight",
    "QuantLibError",
    "VaRResult",
    "bond_risk_metrics",
    "bond_yield_to_maturity",
    "greeks_european_bs",
    "historical_var",
    "parametric_var",
    "price_american_binomial",
    "price_european_bs",
]
