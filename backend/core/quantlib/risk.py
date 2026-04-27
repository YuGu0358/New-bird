"""Value-at-Risk and Conditional VaR.

Uses pure-Python statistics (no QuantLib dependency for VaR — it's
straightforward stats) to keep the wrappers focused. QuantLib is used
only when its primitives genuinely help (option pricing, bond analytics).
"""
from __future__ import annotations

import math
import statistics
from typing import Sequence

from core.quantlib.base import VaRResult


# Cached z-scores for common confidence levels (one-sided lower tail).
_Z_TABLE = {
    0.90: 1.2816,
    0.95: 1.6449,
    0.975: 1.96,
    0.99: 2.3263,
    0.995: 2.5758,
    0.999: 3.0902,
}


def _z_score(confidence: float) -> float:
    """Inverse normal CDF for `confidence` (lower-tail). Uses a table for
    common levels; falls back to Beasley-Springer-Moro for others."""
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")

    if confidence in _Z_TABLE:
        return _Z_TABLE[confidence]

    a = (-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00)

    p = confidence
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def parametric_var(
    *,
    notional: float,
    mean_return: float,
    std_return: float,
    confidence: float,
    horizon_days: int,
) -> VaRResult:
    """Variance-covariance VaR assuming normally distributed returns.

    Inputs are per-period (typically daily) return statistics. We scale to
    `horizon_days` via sqrt(time).
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    if notional <= 0:
        raise ValueError("notional must be > 0")
    if std_return < 0:
        raise ValueError("std_return must be >= 0")

    z = _z_score(confidence)
    horizon_std = std_return * math.sqrt(horizon_days)
    horizon_mean = mean_return * horizon_days

    # VaR is a POSITIVE loss number.
    var = max(0.0, (z * horizon_std - horizon_mean) * notional)

    # Closed-form Normal CVaR: phi(z) / (1 - F(z)) * sigma - mean
    pdf_z = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    cvar = max(0.0, ((pdf_z / (1 - confidence)) * horizon_std - horizon_mean) * notional)

    return VaRResult(
        var=float(var),
        cvar=float(cvar),
        confidence=float(confidence),
        horizon_days=int(horizon_days),
        method="parametric",
    )


def historical_var(
    *,
    notional: float,
    returns: Sequence[float],
    confidence: float,
    horizon_days: int,
) -> VaRResult:
    """Empirical-quantile VaR over a return series.

    `returns` are PER-PERIOD (typically daily). We aggregate to the horizon
    via sqrt-of-time scaling on the empirical loss quantile.
    """
    if len(returns) < 30:
        raise ValueError("Need at least 30 returns for historical VaR")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    if notional <= 0:
        raise ValueError("notional must be > 0")

    sorted_returns = sorted(returns)
    n = len(sorted_returns)
    rank = max(0, min(n - 1, int(math.floor((1 - confidence) * n))))
    quantile_return = sorted_returns[rank]
    # Loss is the magnitude of the negative quantile.
    daily_loss = max(0.0, -quantile_return)
    horizon_loss = daily_loss * math.sqrt(horizon_days)

    # CVaR = mean of returns at or below quantile, taken positive.
    tail = sorted_returns[: rank + 1]
    if tail:
        avg_tail = statistics.fmean(tail)
        daily_cvar = max(0.0, -avg_tail)
    else:
        daily_cvar = daily_loss
    horizon_cvar = daily_cvar * math.sqrt(horizon_days)

    return VaRResult(
        var=float(horizon_loss * notional),
        cvar=float(horizon_cvar * notional),
        confidence=float(confidence),
        horizon_days=int(horizon_days),
        method="historical",
    )
