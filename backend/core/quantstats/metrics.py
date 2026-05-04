"""Standard backtest performance metrics — pure Python, stdlib-only.

Conventions follow J. Zakamouline / Bacon (Practical Portfolio Performance Measurement)
and quantstats defaults:

- Sharpe ratio        : annualized excess-return / annualized stdev
- Sortino ratio       : annualized excess-return / annualized downside stdev
- Max drawdown        : peak-to-trough on cumulative returns (fraction, not %)
- Calmar ratio        : CAGR / |max_drawdown|
- CAGR                : compound annual growth rate from first → last value
- Volatility (annual) : stdev(returns) * sqrt(periods_per_year)

`periods_per_year` defaults to 252 (US trading days). Override for daily-
inclusive (365) or weekly (52) series. Risk-free rate is annualized
fraction (0.04 = 4%) and is converted to per-period in the Sharpe/Sortino
math.

Why no quantstats / pandas: the rest of the codebase keeps perf-critical
math in pure Python (see core/indicators) so this module fits the same
policy. The math is small and the test suite pins reference values.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class TearsheetMetrics:
    cagr: float | None
    volatility: float | None
    sharpe: float | None
    sortino: float | None
    max_drawdown: float | None  # negative number, e.g. -0.15 for -15%
    calmar: float | None
    total_return: float | None  # final / initial - 1
    periods: int


def _to_returns(values: list[float]) -> list[float]:
    """Convert a price/equity series into per-period simple returns.

    Returns list is one shorter than `values`. A zero or negative price
    in `values` short-circuits to a 0.0 return for that step (defensive
    — backtest equity should never go negative, but if it does we don't
    want NaN poisoning Sharpe).
    """
    out: list[float] = []
    for prev, cur in zip(values, values[1:]):
        if prev <= 0:
            out.append(0.0)
            continue
        out.append((cur / prev) - 1.0)
    return out


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    """Sample standard deviation (n-1 denominator)."""
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    var = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def _downside_stdev(values: list[float], threshold: float = 0.0) -> float:
    """Sample stdev of returns below `threshold` (Sortino's denominator)."""
    below = [v for v in values if v < threshold]
    if len(below) < 2:
        return 0.0
    # Sortino convention: deviation from threshold (typically 0), not mean.
    var = sum((v - threshold) ** 2 for v in below) / (len(below) - 1)
    return math.sqrt(var)


def _max_drawdown(values: list[float]) -> float:
    """Peak-to-trough drawdown on the equity curve, returned as a negative
    fraction (e.g. -0.20 for -20%). Empty / single-point series → 0.0.
    """
    peak = float("-inf")
    worst = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < worst:
                worst = dd
    return worst


def compute_tearsheet(
    equity: list[float],
    *,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.04,
) -> TearsheetMetrics:
    """Compute the full tearsheet from an equity-value series.

    `equity[0]` is the starting NAV, `equity[-1]` is the ending NAV.
    Series with fewer than 2 points yield all-None metrics (no math
    possible).
    """
    if len(equity) < 2:
        return TearsheetMetrics(
            cagr=None,
            volatility=None,
            sharpe=None,
            sortino=None,
            max_drawdown=None,
            calmar=None,
            total_return=None,
            periods=len(equity),
        )

    returns = _to_returns(equity)
    if not returns:
        return TearsheetMetrics(
            cagr=None,
            volatility=None,
            sharpe=None,
            sortino=None,
            max_drawdown=None,
            calmar=None,
            total_return=None,
            periods=len(equity),
        )

    initial = equity[0]
    final = equity[-1]
    total_return = (final / initial) - 1.0 if initial > 0 else None

    # CAGR — periods → years.
    years = len(returns) / periods_per_year
    if initial > 0 and final > 0 and years > 0:
        cagr = (final / initial) ** (1.0 / years) - 1.0
    else:
        cagr = None

    vol_per_period = _stdev(returns)
    volatility = vol_per_period * math.sqrt(periods_per_year)

    # Per-period excess return.
    rf_per_period = risk_free_rate / periods_per_year
    avg_excess = _mean(returns) - rf_per_period
    if vol_per_period > 0:
        sharpe = (avg_excess / vol_per_period) * math.sqrt(periods_per_year)
    else:
        sharpe = None

    downside = _downside_stdev(returns, threshold=rf_per_period)
    if downside > 0:
        sortino = (avg_excess / downside) * math.sqrt(periods_per_year)
    else:
        sortino = None

    max_dd = _max_drawdown(equity)
    if cagr is not None and max_dd < 0:
        calmar = cagr / abs(max_dd)
    else:
        calmar = None

    return TearsheetMetrics(
        cagr=cagr,
        volatility=volatility,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        calmar=calmar,
        total_return=total_return,
        periods=len(equity),
    )
