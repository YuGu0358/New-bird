"""Vectorised factor operators.

All operators take 1 to 3 inputs that are either ``pd.Series`` indexed by a
``MultiIndex`` of ``(date, symbol)`` or scalars, and return a ``pd.Series``
with the same index. Implementations rely exclusively on pandas / numpy
vectorised primitives  no Python-level loops over rows.

The :data:`OPS` registry maps operator name -> callable so the AST evaluator
can dispatch by string name.
"""

from __future__ import annotations

from typing import Callable, Dict, Union

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EPS = 1e-12  # numerical floor for log / division
SeriesOrScalar = Union[pd.Series, float, int]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_series(x: SeriesOrScalar, ref: pd.Series | None = None) -> pd.Series:
    """Promote scalars to a series broadcastable with ``ref``.

    If ``ref`` is provided, the scalar is broadcast across its index;
    otherwise the value is returned wrapped in a single-element Series.
    """
    if isinstance(x, pd.Series):
        return x
    if ref is not None:
        return pd.Series(np.full(len(ref), float(x), dtype=float), index=ref.index)
    return pd.Series([float(x)])


def _by_symbol(s: pd.Series) -> "pd.core.groupby.SeriesGroupBy":
    """Group by the ``symbol`` level of the MultiIndex."""
    return s.groupby(level="symbol", group_keys=False, sort=False)


def _by_date(s: pd.Series) -> "pd.core.groupby.SeriesGroupBy":
    """Group by the ``date`` level of the MultiIndex."""
    return s.groupby(level="date", group_keys=False, sort=False)


def _rolling(s: pd.Series, n: int):
    """Rolling object grouped by symbol (drops the symbol from the index)."""
    return _by_symbol(s).rolling(int(n))


def _align(out: pd.Series, ref: pd.Series) -> pd.Series:
    """Reindex ``out`` to ``ref``'s index (handles groupby.rolling re-keying)."""
    if not out.index.equals(ref.index):
        out = out.reindex(ref.index)
    return out


# ---------------------------------------------------------------------------
# Cross-sectional operators (within each date)
# ---------------------------------------------------------------------------


def op_rank(x: pd.Series) -> pd.Series:
    """Cross-sectional rank within each date, scaled to [0, 1]."""
    return _by_date(x).rank(pct=True)


def op_zscore(x: pd.Series) -> pd.Series:
    """Cross-sectional z-score within each date."""
    mean = _by_date(x).transform("mean")
    std = _by_date(x).transform("std")
    return (x - mean) / std.replace(0, np.nan)


def op_quantile(x: pd.Series, q: SeriesOrScalar) -> pd.Series:
    """Bucket each value into one of ``q`` quantiles within its date."""
    q_int = int(q if not isinstance(q, pd.Series) else q.iloc[0])
    q_int = max(2, q_int)

    def _bucket(group: pd.Series) -> pd.Series:
        try:
            return pd.qcut(group, q_int, labels=False, duplicates="drop").astype(float)
        except (ValueError, TypeError):
            return pd.Series(np.nan, index=group.index)

    return _by_date(x).transform(_bucket)


def op_industry_neutral(x: pd.Series, industry: pd.Series) -> pd.Series:
    """Subtract the per-date industry mean from ``x``."""
    df = pd.DataFrame({"x": x, "ind": industry})
    grp_mean = df.groupby([df.index.get_level_values("date"), "ind"])["x"].transform(
        "mean"
    )
    return x - grp_mean


def op_market_cap_neutral(x: pd.Series, mcap: pd.Series) -> pd.Series:
    """Regress ``x`` on ``log(mcap)`` per date and return the residuals."""
    log_mcap = np.log(mcap.abs() + EPS)

    def _residual(group: pd.DataFrame) -> pd.Series:
        y = group["x"].to_numpy()
        z = group["m"].to_numpy()
        mask = np.isfinite(y) & np.isfinite(z)
        if mask.sum() < 2:
            return pd.Series(np.nan, index=group.index)
        slope, intercept = np.polyfit(z[mask], y[mask], 1)
        residuals = y - (slope * z + intercept)
        return pd.Series(residuals, index=group.index)

    df = pd.DataFrame({"x": x, "m": log_mcap})
    out = df.groupby(level="date", group_keys=False).apply(_residual)
    return _align(out, x)


def op_min_max_scale(x: pd.Series) -> pd.Series:
    """Scale each date's values to [0, 1]."""
    lo = _by_date(x).transform("min")
    hi = _by_date(x).transform("max")
    rng = (hi - lo).replace(0, np.nan)
    return (x - lo) / rng


# ---------------------------------------------------------------------------
# Time-series operators (per symbol over time)
# ---------------------------------------------------------------------------


def op_ts_mean(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    return _align(_rolling(x, int(n)).mean().reset_index(level=0, drop=True), x)


def op_ts_std(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    return _align(_rolling(x, int(n)).std().reset_index(level=0, drop=True), x)


def op_ts_min(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    return _align(_rolling(x, int(n)).min().reset_index(level=0, drop=True), x)


def op_ts_max(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    return _align(_rolling(x, int(n)).max().reset_index(level=0, drop=True), x)


def op_ts_sum(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    return _align(_rolling(x, int(n)).sum().reset_index(level=0, drop=True), x)


def op_ts_argmin(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    """Bars-since-min over the trailing ``n`` window (0 means current bar)."""
    win = int(n)
    out = _rolling(x, win).apply(
        lambda v: float(win - 1 - np.argmin(v)), raw=True
    )
    return _align(out.reset_index(level=0, drop=True), x)


def op_ts_argmax(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    """Bars-since-max over the trailing ``n`` window (0 means current bar)."""
    win = int(n)
    out = _rolling(x, win).apply(
        lambda v: float(win - 1 - np.argmax(v)), raw=True
    )
    return _align(out.reset_index(level=0, drop=True), x)


def op_ts_rank(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    """Rank of the current value vs the trailing ``n`` window, in [0, 1]."""
    win = int(n)

    def _r(v: np.ndarray) -> float:
        last = v[-1]
        if not np.isfinite(last):
            return np.nan
        return float((v <= last).sum() - 1) / max(1, len(v) - 1)

    out = _rolling(x, win).apply(_r, raw=True)
    return _align(out.reset_index(level=0, drop=True), x)


def op_delta(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    """``x - x.shift(n)`` per symbol."""
    shifted = _by_symbol(x).shift(int(n))
    return x - shifted


def op_delay(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    """``x.shift(n)`` per symbol."""
    return _by_symbol(x).shift(int(n))


def op_decay_linear(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    """Linearly weighted moving average  most recent observation gets weight ``n``."""
    win = int(n)
    weights = np.arange(1, win + 1, dtype=float)
    weights = weights / weights.sum()

    def _wmean(v: np.ndarray) -> float:
        if np.isnan(v).any():
            return np.nan
        return float(np.dot(v, weights))

    out = _rolling(x, win).apply(_wmean, raw=True)
    return _align(out.reset_index(level=0, drop=True), x)


def op_correlation(x: pd.Series, y: pd.Series, n: SeriesOrScalar) -> pd.Series:
    win = int(n)
    df = pd.DataFrame({"x": x, "y": y})
    out = df.groupby(level="symbol", group_keys=False, sort=False).apply(
        lambda g: g["x"].rolling(win).corr(g["y"])
    )
    return _align(out, x)


def op_covariance(x: pd.Series, y: pd.Series, n: SeriesOrScalar) -> pd.Series:
    win = int(n)
    df = pd.DataFrame({"x": x, "y": y})
    out = df.groupby(level="symbol", group_keys=False, sort=False).apply(
        lambda g: g["x"].rolling(win).cov(g["y"])
    )
    return _align(out, x)


def op_regression_neutral(
    x: pd.Series, y: pd.Series, n: SeriesOrScalar
) -> pd.Series:
    """Residual of x ~ y in a rolling ``n`` window per symbol."""
    win = int(n)
    cov = op_covariance(x, y, win)
    var_y = op_ts_std(y, win) ** 2
    beta = cov / var_y.replace(0, np.nan)
    mean_x = op_ts_mean(x, win)
    mean_y = op_ts_mean(y, win)
    alpha = mean_x - beta * mean_y
    return x - (alpha + beta * y)


def op_ema(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    span = int(n)
    out = _by_symbol(x).apply(lambda g: g.ewm(span=span, adjust=False).mean())
    return _align(out, x)


def op_sma(x: pd.Series, n: SeriesOrScalar) -> pd.Series:
    """Alias for ts_mean."""
    return op_ts_mean(x, n)


# ---------------------------------------------------------------------------
# Element-wise operators
# ---------------------------------------------------------------------------


def _binary(a: SeriesOrScalar, b: SeriesOrScalar, fn) -> pd.Series:
    if isinstance(a, pd.Series) and isinstance(b, pd.Series):
        return fn(a, b)
    if isinstance(a, pd.Series):
        return fn(a, _as_series(b, ref=a))
    if isinstance(b, pd.Series):
        return fn(_as_series(a, ref=b), b)
    return pd.Series([fn(float(a), float(b))])


def op_add(a: SeriesOrScalar, b: SeriesOrScalar) -> pd.Series:
    return _binary(a, b, lambda x, y: x + y)


def op_sub(a: SeriesOrScalar, b: SeriesOrScalar) -> pd.Series:
    return _binary(a, b, lambda x, y: x - y)


def op_mul(a: SeriesOrScalar, b: SeriesOrScalar) -> pd.Series:
    return _binary(a, b, lambda x, y: x * y)


def op_div(a: SeriesOrScalar, b: SeriesOrScalar) -> pd.Series:
    """Safe division  returns 0 when the denominator is zero / non-finite."""
    def _safe(x: pd.Series, y: pd.Series) -> pd.Series:
        denom = y.where((y != 0) & np.isfinite(y), np.nan)
        result = x / denom
        return result.fillna(0.0)

    return _binary(a, b, _safe)


def op_neg(x: pd.Series) -> pd.Series:
    return -x if isinstance(x, pd.Series) else pd.Series([-float(x)])


def op_abs(x: pd.Series) -> pd.Series:
    return x.abs() if isinstance(x, pd.Series) else pd.Series([abs(float(x))])


def op_sign(x: pd.Series) -> pd.Series:
    if isinstance(x, pd.Series):
        return np.sign(x)
    return pd.Series([float(np.sign(x))])


def op_log(x: pd.Series) -> pd.Series:
    """Sign-preserving log: ``sign(x) * log(|x| + eps)``."""
    if not isinstance(x, pd.Series):
        x = _as_series(x)
    return np.sign(x) * np.log(x.abs() + EPS)


def op_sqrt(x: pd.Series) -> pd.Series:
    """Sign-preserving sqrt: ``sign(x) * sqrt(|x|)``."""
    if not isinstance(x, pd.Series):
        x = _as_series(x)
    return np.sign(x) * np.sqrt(x.abs())


def op_power(x: pd.Series, k: SeriesOrScalar) -> pd.Series:
    """Sign-preserving power: ``sign(x) * |x|**k``."""
    if not isinstance(x, pd.Series):
        x = _as_series(x)
    k_val = float(k if not isinstance(k, pd.Series) else k.iloc[0])
    return np.sign(x) * np.power(x.abs(), k_val)


def op_if_else(
    cond: SeriesOrScalar, a: SeriesOrScalar, b: SeriesOrScalar
) -> pd.Series:
    """Element-wise ``np.where(cond > 0, a, b)``."""
    ref = next(
        (z for z in (cond, a, b) if isinstance(z, pd.Series)), None
    )
    if ref is None:
        return pd.Series([float(a) if float(cond) > 0 else float(b)])
    cond_s = _as_series(cond, ref=ref)
    a_s = _as_series(a, ref=ref)
    b_s = _as_series(b, ref=ref)
    return pd.Series(np.where(cond_s > 0, a_s, b_s), index=ref.index)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


OPS: Dict[str, Callable] = {
    # cross-sectional
    "rank": op_rank,
    "zscore": op_zscore,
    "quantile": op_quantile,
    "industry_neutral": op_industry_neutral,
    "market_cap_neutral": op_market_cap_neutral,
    "min_max_scale": op_min_max_scale,
    # time-series
    "ts_mean": op_ts_mean,
    "ts_std": op_ts_std,
    "ts_min": op_ts_min,
    "ts_max": op_ts_max,
    "ts_sum": op_ts_sum,
    "ts_argmin": op_ts_argmin,
    "ts_argmax": op_ts_argmax,
    "ts_rank": op_ts_rank,
    "delta": op_delta,
    "delay": op_delay,
    "decay_linear": op_decay_linear,
    "correlation": op_correlation,
    "covariance": op_covariance,
    "regression_neutral": op_regression_neutral,
    "ema": op_ema,
    "sma": op_sma,
    # element-wise
    "add": op_add,
    "sub": op_sub,
    "mul": op_mul,
    "div": op_div,
    "neg": op_neg,
    "abs": op_abs,
    "sign": op_sign,
    "log": op_log,
    "sqrt": op_sqrt,
    "power": op_power,
    "if_else": op_if_else,
}
