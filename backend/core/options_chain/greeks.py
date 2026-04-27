"""Black-Scholes Greeks for European options.

We re-implement the lightweight scipy-only version even though `core.quantlib`
has a richer one — yfinance gives us IV but not gamma, so the chain pipeline
needs gamma per row to compute GEX, and we don't want to hard-depend on
QuantLib for this code path. Both implementations should agree on the
4 standard Greeks for vanilla European options.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm

SQRT_2PI = math.sqrt(2 * math.pi)


@dataclass(frozen=True)
class Greeks:
    delta: float
    gamma: float
    theta: float
    vega: float


def _phi(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def black_scholes_greeks(
    *,
    spot: float,
    strike: float,
    time_to_expiry_yrs: float,
    iv: float,
    r: float = 0.04,
    q: float = 0.0,
    option_type: str = "C",
) -> Greeks | None:
    """Return Δ Γ Θ V for a European option. None if inputs are degenerate."""
    if time_to_expiry_yrs <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return None
    sigma_sqrt_t = iv * math.sqrt(time_to_expiry_yrs)
    if sigma_sqrt_t == 0:
        return None

    d1 = (math.log(spot / strike) + (r - q + 0.5 * iv * iv) * time_to_expiry_yrs) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t

    pdf_d1 = _phi(d1)
    cdf_d1 = norm.cdf(d1)
    cdf_d2 = norm.cdf(d2)

    gamma_val = math.exp(-q * time_to_expiry_yrs) * pdf_d1 / (spot * sigma_sqrt_t)
    vega_val = spot * math.exp(-q * time_to_expiry_yrs) * pdf_d1 * math.sqrt(time_to_expiry_yrs)

    if option_type.upper() == "C":
        delta_val = math.exp(-q * time_to_expiry_yrs) * cdf_d1
        theta_val = (
            -spot * pdf_d1 * iv * math.exp(-q * time_to_expiry_yrs) / (2 * math.sqrt(time_to_expiry_yrs))
            - r * strike * math.exp(-r * time_to_expiry_yrs) * cdf_d2
            + q * spot * math.exp(-q * time_to_expiry_yrs) * cdf_d1
        )
    else:
        delta_val = math.exp(-q * time_to_expiry_yrs) * (cdf_d1 - 1)
        theta_val = (
            -spot * pdf_d1 * iv * math.exp(-q * time_to_expiry_yrs) / (2 * math.sqrt(time_to_expiry_yrs))
            + r * strike * math.exp(-r * time_to_expiry_yrs) * norm.cdf(-d2)
            - q * spot * math.exp(-q * time_to_expiry_yrs) * norm.cdf(-d1)
        )

    return Greeks(
        delta=delta_val,
        gamma=gamma_val,
        theta=theta_val / 365.0,  # daily theta
        vega=vega_val / 100.0,    # per 1% IV change
    )
