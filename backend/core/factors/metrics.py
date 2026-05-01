"""Pure metric helpers for the factor backtest engine.

These functions are dependency-light (numpy / pandas only — scipy is used
opportunistically when present) and side-effect free. They are unit-tested
in ``tests/test_factor_metrics.py`` without touching the database.

Conventions
-----------
- All inputs may contain NaN; helpers must drop / mask defensively.
- Return ``float('nan')`` for any case where the metric is undefined
  (insufficient data, zero variance, no drawdown, etc.). The caller (the
  backtest service) maps ``NaN`` → ``fitness=-99.0`` so GP search can
  prune failed candidates.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

try:  # pragma: no cover - import-time fallback
    from scipy.stats import spearmanr as _scipy_spearmanr  # type: ignore

    _HAS_SCIPY = True
except ImportError:  # pragma: no cover
    _scipy_spearmanr = None  # type: ignore
    _HAS_SCIPY = False


TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# Information coefficients
# ---------------------------------------------------------------------------


def _align_finite(a: pd.Series | np.ndarray, b: pd.Series | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return matched-length numpy arrays with rows containing NaN dropped."""
    arr_a = np.asarray(a, dtype=float).ravel()
    arr_b = np.asarray(b, dtype=float).ravel()
    if arr_a.shape != arr_b.shape:
        raise ValueError(
            f"Shape mismatch: {arr_a.shape} vs {arr_b.shape}"
        )
    mask = np.isfinite(arr_a) & np.isfinite(arr_b)
    return arr_a[mask], arr_b[mask]


def pearson_ic(scores: pd.Series | np.ndarray, returns: pd.Series | np.ndarray) -> float:
    """Pearson correlation between scores and returns (NaN-safe)."""
    a, b = _align_finite(scores, returns)
    if a.size < 3:
        return float("nan")
    if np.std(a) == 0.0 or np.std(b) == 0.0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def spearman_ic(scores: pd.Series | np.ndarray, returns: pd.Series | np.ndarray) -> float:
    """Spearman rank correlation (NaN-safe).

    Falls back to ``pearson_ic`` of the ranks when scipy is not installed.
    """
    a, b = _align_finite(scores, returns)
    if a.size < 3:
        return float("nan")
    if _HAS_SCIPY:
        rho, _p = _scipy_spearmanr(a, b)
        if rho is None or np.isnan(rho):
            return 0.0
        return float(rho)
    # Hand-rolled Spearman: rank both vectors then take Pearson.
    ranks_a = pd.Series(a).rank(method="average").to_numpy()
    ranks_b = pd.Series(b).rank(method="average").to_numpy()
    if np.std(ranks_a) == 0.0 or np.std(ranks_b) == 0.0:
        return 0.0
    return float(np.corrcoef(ranks_a, ranks_b)[0, 1])


# ---------------------------------------------------------------------------
# Portfolio summary stats
# ---------------------------------------------------------------------------


def sharpe(returns: Sequence[float] | np.ndarray | pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Annualized Sharpe ratio (zero risk-free rate)."""
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return float("nan")
    mean = arr.mean()
    std = arr.std(ddof=1)
    if std == 0.0:
        return float("nan")
    return float((mean / std) * np.sqrt(periods_per_year))


def sortino(returns: Sequence[float] | np.ndarray | pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Annualized Sortino ratio (downside-only std)."""
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return float("nan")
    mean = arr.mean()
    downside = arr[arr < 0.0]
    if downside.size < 2:
        return float("nan")
    dstd = downside.std(ddof=1)
    if dstd == 0.0:
        return float("nan")
    return float((mean / dstd) * np.sqrt(periods_per_year))


def max_drawdown(equity_curve: Sequence[float] | np.ndarray | pd.Series) -> float:
    """Peak-to-trough max drawdown as a positive fraction.

    The input is an *equity curve* (cumulative wealth, e.g. starts at 1.0),
    NOT a returns series.
    """
    arr = np.asarray(equity_curve, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return float("nan")
    running_peak = np.maximum.accumulate(arr)
    drawdowns = (running_peak - arr) / running_peak
    dd = float(np.nanmax(drawdowns))
    return dd if dd > 0.0 else 0.0


def calmar(returns: Sequence[float] | np.ndarray | pd.Series, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Annualized return / max drawdown computed from a returns series."""
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return float("nan")
    equity = np.cumprod(1.0 + arr)
    mdd = max_drawdown(equity)
    if not np.isfinite(mdd) or mdd == 0.0:
        return float("nan")
    annualized = arr.mean() * periods_per_year
    return float(annualized / mdd)


def turnover(baskets: Iterable[Iterable[Any]]) -> float:
    """Mean per-day turnover of a sequence of basket symbol-sets.

    Each transition counts ``(|removed| + |added|) / 2 / max(|prev|, |curr|)``
    so a one-symbol swap on a size-N basket reads as ``1/N``. Returns NaN
    when fewer than two non-empty baskets are provided.
    """
    sets = [frozenset(b) for b in baskets if b is not None]
    sets = [s for s in sets if len(s) > 0]
    if len(sets) < 2:
        return float("nan")
    diffs: list[float] = []
    for prev, curr in zip(sets, sets[1:]):
        denom = max(len(prev), len(curr))
        if denom == 0:
            continue
        # symmetric difference counts each swap twice (one out + one in),
        # so divide by 2 to express turnover as a fraction of basket size.
        changed = len(prev.symmetric_difference(curr)) / 2
        diffs.append(changed / denom)
    if not diffs:
        return float("nan")
    return float(np.mean(diffs))


__all__ = [
    "TRADING_DAYS_PER_YEAR",
    "pearson_ic",
    "spearman_ic",
    "sharpe",
    "sortino",
    "max_drawdown",
    "calmar",
    "turnover",
]
