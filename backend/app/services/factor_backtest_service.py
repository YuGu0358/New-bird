"""Factor Forge: vectorized backtest engine.

Given a factor formula (string or :class:`FactorNode`) and a date range,
this service:

1. Loads the OHLCV panel (or accepts one for tests).
2. Computes forward returns at 1d / 5d / 20d horizons.
3. Evaluates the factor scores via :mod:`core.factors.eval`.
4. Restricts each day to its top-N "active universe".
5. Reports per-horizon ICs + ICIR + rank-IC.
6. Builds a daily-rebalanced long/short quintile portfolio at the 5d
   horizon and reports Sharpe / Sortino / Calmar / max DD / win rate /
   turnover.
7. Composes a fitness score ``w · IC`` (default weights = (0.2, 0.5, 0.3)).

If anything blows up — empty panel, all-NaN scores, constant scores,
insufficient days — we return a :class:`BacktestResult` with
``fitness=-99.0`` so genetic search can drop the candidate cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from core.factors import FactorNode, evaluate, parse
from core.factors.metrics import (
    TRADING_DAYS_PER_YEAR,
    calmar,
    max_drawdown,
    pearson_ic,
    sharpe,
    sortino,
    spearman_ic,
    turnover,
)

logger = logging.getLogger(__name__)


FAILED_FITNESS = -99.0
DEFAULT_FITNESS_WEIGHTS: tuple[float, float, float] = (0.2, 0.5, 0.3)
DEFAULT_QUANTILES = 5
DEFAULT_UNIVERSE_SIZE = 100
RETURN_CURVE_SAMPLES = 64
MIN_DAYS_FOR_PORTFOLIO = 5
HORIZONS: tuple[int, int, int] = (1, 5, 20)


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestResult:
    """Backtest summary for a single factor formula."""

    formula: str
    fitness: float
    ic_1d: float
    ic_5d: float
    ic_20d: float
    icir_5d: float
    rank_ic_5d: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    turnover: float
    win_rate: float
    n_days: int
    n_obs: int
    return_curve: list[float] = field(default_factory=list)


def _failed_result(formula: str, *, n_obs: int = 0, n_days: int = 0) -> BacktestResult:
    nan = float("nan")
    return BacktestResult(
        formula=formula,
        fitness=FAILED_FITNESS,
        ic_1d=nan,
        ic_5d=nan,
        ic_20d=nan,
        icir_5d=nan,
        rank_ic_5d=nan,
        sharpe=nan,
        sortino=nan,
        calmar=nan,
        max_drawdown=nan,
        turnover=nan,
        win_rate=nan,
        n_days=n_days,
        n_obs=n_obs,
        return_curve=[],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_node(formula: str | FactorNode) -> FactorNode:
    if isinstance(formula, FactorNode):
        return formula
    if isinstance(formula, str):
        return parse(formula)
    raise TypeError(f"Unsupported formula type: {type(formula).__name__}")


async def load_sector_map() -> dict[str, str]:
    """Load symbol → sector mapping from factor_symbol_meta.

    Returns ``{}`` when the table is empty (caller falls back to no
    sector neutralization). Symbols without a sector show up as
    ``UNKNOWN``, treated as their own bucket.
    """
    from sqlalchemy import select

    from app.db.engine import AsyncSessionLocal
    from app.db.tables import SymbolMeta

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SymbolMeta.symbol, SymbolMeta.sector)
            )
        ).all()
    if not rows:
        return {}
    return {sym: sec or "UNKNOWN" for sym, sec in rows}


def _neutralize_by_sector(
    values: pd.Series, sector_map: dict[str, str] | None
) -> pd.Series:
    """Cross-sectional sector demean: subtract per-(date, sector) mean.

    Strips out sector beta exposure so the IC measures within-sector
    stock-picking edge rather than sector-rotation timing. Symbols
    missing from ``sector_map`` are bucketed as ``UNKNOWN`` and
    demeaned together. Returns the input unchanged when ``sector_map``
    is empty / None.

    NaN-safe: the per-group mean is computed with skipna=True; missing
    cells stay missing.
    """
    if not sector_map:
        return values
    if values.empty:
        return values
    df = values.rename("v").reset_index()
    if "symbol" not in df.columns or "date" not in df.columns:
        return values
    df["sector"] = df["symbol"].map(sector_map).fillna("UNKNOWN")
    df["sector_mean"] = df.groupby(["date", "sector"])["v"].transform("mean")
    df["v_neutral"] = df["v"] - df["sector_mean"]
    return df.set_index(["date", "symbol"])["v_neutral"]


def _compute_forward_returns(panel: pd.DataFrame, horizon: int) -> pd.Series:
    """Per-symbol forward return over ``horizon`` trading days.

    Vectorized via groupby on the symbol level — no per-symbol Python
    loop. The result is shifted backwards so that row ``t`` carries the
    return realised between ``t`` and ``t+horizon``.
    """
    close = panel["close"]
    fwd = close.groupby(level="symbol").transform(
        lambda s: s.pct_change(horizon).shift(-horizon)
    )
    return fwd.rename(f"r_{horizon}d")


def _spearman_per_date(group: pd.DataFrame) -> float:
    return spearman_ic(group["score"].to_numpy(), group["ret"].to_numpy())


def _pearson_per_date(group: pd.DataFrame) -> float:
    return pearson_ic(group["score"].to_numpy(), group["ret"].to_numpy())


def _daily_ic_series(scores: pd.Series, returns: pd.Series, *, rank_based: bool) -> pd.Series:
    """Return one IC per date, vectorized via a single ``groupby``."""
    df = pd.DataFrame({"score": scores, "ret": returns}).dropna()
    if df.empty:
        return pd.Series(dtype=float)
    func = _spearman_per_date if rank_based else _pearson_per_date
    return df.groupby(level="date", sort=True).apply(func)


def _sample_curve(equity: np.ndarray, n: int = RETURN_CURVE_SAMPLES) -> list[float]:
    """Return ``n`` evenly-spaced samples of ``equity - 1`` (cumulative return)."""
    if equity.size == 0:
        return []
    cum_ret = (equity - 1.0).astype(float)
    if cum_ret.size >= n:
        idx = np.linspace(0, cum_ret.size - 1, n).round().astype(int)
        return cum_ret[idx].tolist()
    # pad with the final value so embeddings stay shape-stable.
    out = cum_ret.tolist()
    pad_value = out[-1] if out else 0.0
    out.extend([pad_value] * (n - len(out)))
    return out


# ---------------------------------------------------------------------------
# Pure metric pipeline (no DB)
# ---------------------------------------------------------------------------


def compute_metrics(
    scores: pd.Series,
    returns_panel: pd.DataFrame,
    *,
    universe_mask: pd.Series | None = None,
    quantiles: int = DEFAULT_QUANTILES,
    fitness_weights: tuple[float, float, float] = DEFAULT_FITNESS_WEIGHTS,
    sector_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Compute all metrics from pre-computed scores and forward returns.

    Pure function — useful for unit tests with a synthetic panel.

    Parameters
    ----------
    scores : pd.Series
        MultiIndex (date, symbol) factor values.
    returns_panel : pd.DataFrame
        MultiIndex (date, symbol) with columns ``r_1d``, ``r_5d``, ``r_20d``.
    universe_mask : pd.Series, optional
        Boolean MultiIndex (date, symbol) — True where the (date, symbol)
        cell is in that day's active universe. If omitted, all rows count.
    sector_map : dict[str, str], optional
        Symbol → sector mapping. When provided, scores are
        cross-sectionally demeaned by (date, sector) before IC and
        long-short basket construction. Strips sector-rotation beta so
        the IC measures genuine within-sector stock-picking edge.
    """
    if scores.empty or returns_panel.empty:
        return {"failed": True, "n_obs": 0, "n_days": 0}

    # Align scores onto the panel's index, applying the universe mask.
    scores_aligned = scores.reindex(returns_panel.index)
    if universe_mask is not None:
        masked_idx = universe_mask.reindex(returns_panel.index).fillna(False).astype(bool)
        scores_aligned = scores_aligned.where(masked_idx)

    # Sector neutralization — strip per-day sector mean so the IC
    # measures within-sector ranking, not sector beta. Falls back to
    # raw scores when sector_map is empty.
    if sector_map:
        scores_aligned = _neutralize_by_sector(scores_aligned, sector_map)

    if not np.isfinite(scores_aligned.to_numpy(dtype=float, na_value=np.nan)).any():
        return {"failed": True, "n_obs": 0, "n_days": 0}

    # ------------------------------------------------------------------
    # ICs per horizon
    # ------------------------------------------------------------------
    ic_means: dict[int, float] = {}
    ic_series_5d: pd.Series | None = None
    rank_ic_5d_value = float("nan")
    for h in HORIZONS:
        col = f"r_{h}d"
        if col not in returns_panel.columns:
            ic_means[h] = float("nan")
            continue
        ic_series = _daily_ic_series(
            scores_aligned, returns_panel[col], rank_based=False
        )
        ic_means[h] = float(ic_series.mean()) if not ic_series.empty else float("nan")
        if h == 5:
            ic_series_5d = ic_series
            rank_series = _daily_ic_series(
                scores_aligned, returns_panel[col], rank_based=True
            )
            rank_ic_5d_value = (
                float(rank_series.mean()) if not rank_series.empty else float("nan")
            )

    # ICIR at 5d horizon
    icir_5d_value = float("nan")
    if ic_series_5d is not None and ic_series_5d.size >= 2:
        std = ic_series_5d.std(ddof=1)
        if std and np.isfinite(std) and std > 0:
            icir_5d_value = float(ic_series_5d.mean() / std)

    # ------------------------------------------------------------------
    # Long-short portfolio at 5d horizon (daily reweighting; weight 1/5
    # absorbed into the natural pct_change(5) shift — we just take the
    # per-day mean(top) - mean(bot) and treat each day as one period).
    # ------------------------------------------------------------------
    pf_returns: list[float] = []
    long_baskets: list[frozenset[str]] = []

    if "r_5d" in returns_panel.columns:
        df = pd.DataFrame(
            {"score": scores_aligned, "ret": returns_panel["r_5d"]}
        ).dropna()
        if not df.empty:
            for trade_date, group in df.groupby(level="date", sort=True):
                if len(group) < quantiles:
                    continue
                qcut = pd.qcut(
                    group["score"], quantiles, labels=False, duplicates="drop"
                )
                if qcut.isna().all():
                    continue
                top_label = int(np.nanmax(qcut))
                bot_label = int(np.nanmin(qcut))
                if top_label == bot_label:
                    continue
                top = group.loc[qcut == top_label, "ret"]
                bot = group.loc[qcut == bot_label, "ret"]
                if top.empty or bot.empty:
                    continue
                pf_ret = float(top.mean() - bot.mean())
                if not np.isfinite(pf_ret):
                    continue
                pf_returns.append(pf_ret)
                long_syms = group.loc[qcut == top_label].index.get_level_values(
                    "symbol"
                )
                long_baskets.append(frozenset(map(str, long_syms)))

    pf_arr = np.asarray(pf_returns, dtype=float)
    if pf_arr.size < MIN_DAYS_FOR_PORTFOLIO:
        sharpe_val = float("nan")
        sortino_val = float("nan")
        calmar_val = float("nan")
        mdd_val = float("nan")
        win_rate_val = float("nan")
        equity_curve: list[float] = []
    else:
        sharpe_val = sharpe(pf_arr)
        sortino_val = sortino(pf_arr)
        calmar_val = calmar(pf_arr)
        equity = np.cumprod(1.0 + pf_arr)
        mdd_val = max_drawdown(equity)
        win_rate_val = float((pf_arr > 0).mean())
        equity_curve = _sample_curve(equity)
        if equity_curve and equity_curve[0] != 0.0:
            # Sanity: prepend 0 so callers can stitch into a chart cleanly.
            # We sample including endpoints so this is rarely needed.
            pass

    turnover_val = turnover(long_baskets) if long_baskets else float("nan")

    # ------------------------------------------------------------------
    # Composite fitness — only valid if all three IC means are finite.
    # ------------------------------------------------------------------
    weights = fitness_weights
    ics = (ic_means.get(1, float("nan")), ic_means.get(5, float("nan")), ic_means.get(20, float("nan")))
    if all(np.isfinite(v) for v in ics):
        fitness_val = float(weights[0] * ics[0] + weights[1] * ics[1] + weights[2] * ics[2])
    else:
        fitness_val = FAILED_FITNESS

    n_days = int(scores_aligned.dropna().index.get_level_values("date").nunique())
    n_obs = int(scores_aligned.dropna().shape[0])

    return {
        "failed": False,
        "fitness": fitness_val,
        "ic_1d": ics[0],
        "ic_5d": ics[1],
        "ic_20d": ics[2],
        "icir_5d": icir_5d_value,
        "rank_ic_5d": rank_ic_5d_value,
        "sharpe": sharpe_val,
        "sortino": sortino_val,
        "calmar": calmar_val,
        "max_drawdown": mdd_val,
        "turnover": turnover_val,
        "win_rate": win_rate_val,
        "n_days": n_days,
        "n_obs": n_obs,
        "return_curve": equity_curve,
    }


# ---------------------------------------------------------------------------
# Universe loading
# ---------------------------------------------------------------------------


_UNIVERSE_MIN_DATES = 5  # if fewer distinct dates of universe coverage in the
                          # requested range, treat as empty so the caller falls
                          # back to the full panel rather than masking out
                          # everything.


async def load_universe_panel(start: date, end: date) -> pd.Series:
    """Return a boolean MultiIndex Series (date, symbol) of universe membership.

    One round-trip to ``factor_daily_active_universe`` rather than N. Empty
    if no universe rows exist for the range — caller should treat ``None``
    universe mask as "include all symbols".

    Sparse coverage (fewer than ``_UNIVERSE_MIN_DATES`` distinct dates) is
    also treated as empty: a 2-year backtest with only a single day of
    universe data would mask away ~99.9% of observations and force every
    metric to FAILED_FITNESS. On a fresh deploy where ``update_active_universe``
    has only run for today, that's exactly what happened.
    """
    from sqlalchemy import select

    from app.db.engine import AsyncSessionLocal
    from app.db.tables import DailyActiveUniverse

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyActiveUniverse.date, DailyActiveUniverse.symbol).where(
                    DailyActiveUniverse.date >= start,
                    DailyActiveUniverse.date <= end,
                )
            )
        ).all()
    if not rows:
        return pd.Series(dtype=bool)
    df = pd.DataFrame(rows, columns=["date", "symbol"])
    if df["date"].nunique() < _UNIVERSE_MIN_DATES:
        return pd.Series(dtype=bool)
    df["in_universe"] = True
    return df.set_index(["date", "symbol"])["in_universe"].astype(bool)


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def backtest_factor(
    formula: str | FactorNode,
    *,
    start: date,
    end: date,
    universe_size: int = DEFAULT_UNIVERSE_SIZE,
    quantiles: int = DEFAULT_QUANTILES,
    fitness_weights: tuple[float, float, float] = DEFAULT_FITNESS_WEIGHTS,
    panel: pd.DataFrame | None = None,
) -> BacktestResult:
    """Backtest a factor over [start, end]."""

    formula_str = formula if isinstance(formula, str) else str(formula)
    try:
        node = _resolve_node(formula)
        formula_str = str(node)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to parse factor formula %r", formula)
        return _failed_result(str(formula))

    try:
        if panel is None:
            from app.services.factor_data_service import get_panel as _get_panel

            panel = await _get_panel(start, end)
        if panel is None or panel.empty:
            return _failed_result(formula_str)

        # Forward returns for each horizon.
        returns_panel = pd.concat(
            [_compute_forward_returns(panel, h) for h in HORIZONS],
            axis=1,
        )

        scores = evaluate(node, panel)
        if scores is None or scores.empty:
            return _failed_result(formula_str)

        # Try to load universe mask; tolerate failure (e.g. no DB in tests).
        universe_mask: pd.Series | None = None
        if panel is not None and not panel.empty:
            try:
                universe_mask = await load_universe_panel(start, end)
                if universe_mask.empty:
                    universe_mask = None
            except Exception:  # noqa: BLE001
                logger.debug("load_universe_panel failed; using full panel", exc_info=True)
                universe_mask = None

        # Sector map for cross-sectional sector neutralization. Tolerant
        # of missing meta — quality just degrades to non-neutralized IC.
        sector_map: dict[str, str] = {}
        try:
            sector_map = await load_sector_map()
        except Exception:  # noqa: BLE001
            logger.debug("load_sector_map failed; computing without sector neutralization", exc_info=True)

        metrics = compute_metrics(
            scores,
            returns_panel,
            universe_mask=universe_mask,
            quantiles=quantiles,
            fitness_weights=fitness_weights,
            sector_map=sector_map or None,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Backtest failed for formula %r", formula_str)
        return _failed_result(formula_str)

    if metrics.get("failed"):
        return _failed_result(
            formula_str,
            n_obs=int(metrics.get("n_obs", 0)),
            n_days=int(metrics.get("n_days", 0)),
        )

    return BacktestResult(
        formula=formula_str,
        fitness=float(metrics["fitness"]),
        ic_1d=float(metrics["ic_1d"]),
        ic_5d=float(metrics["ic_5d"]),
        ic_20d=float(metrics["ic_20d"]),
        icir_5d=float(metrics["icir_5d"]),
        rank_ic_5d=float(metrics["rank_ic_5d"]),
        sharpe=float(metrics["sharpe"]),
        sortino=float(metrics["sortino"]),
        calmar=float(metrics["calmar"]),
        max_drawdown=float(metrics["max_drawdown"]),
        turnover=float(metrics["turnover"]),
        win_rate=float(metrics["win_rate"]),
        n_days=int(metrics["n_days"]),
        n_obs=int(metrics["n_obs"]),
        return_curve=list(metrics["return_curve"]),
    )


def backtest_factor_sync(
    formula: str | FactorNode,
    *,
    start: date,
    end: date,
    universe_size: int = DEFAULT_UNIVERSE_SIZE,
    quantiles: int = DEFAULT_QUANTILES,
    fitness_weights: tuple[float, float, float] = DEFAULT_FITNESS_WEIGHTS,
    panel: pd.DataFrame | None = None,
) -> BacktestResult:
    """Synchronous wrapper for callers outside an event loop."""
    return asyncio.run(
        backtest_factor(
            formula,
            start=start,
            end=end,
            universe_size=universe_size,
            quantiles=quantiles,
            fitness_weights=fitness_weights,
            panel=panel,
        )
    )


__all__ = [
    "BacktestResult",
    "FAILED_FITNESS",
    "DEFAULT_FITNESS_WEIGHTS",
    "backtest_factor",
    "backtest_factor_sync",
    "compute_metrics",
    "load_sector_map",
    "load_universe_panel",
]
