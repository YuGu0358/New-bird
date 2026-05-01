"""Integration tests for app.services.factor_backtest_service.

We synthesize panels in-memory and pass them via the ``panel=`` kwarg so
the tests never hit the DB or network. The active-universe loader is
patched to return an empty Series ("use full panel").
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services.factor_backtest_service import (
    BacktestResult,
    FAILED_FITNESS,
    backtest_factor,
    compute_metrics,
)
from core.factors import parse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trading_days(n: int) -> pd.DatetimeIndex:
    """``n`` consecutive business days starting 2024-01-02."""
    return pd.bdate_range(start=date(2024, 1, 2), periods=n)


def _build_panel(n_days: int, signal_strength: float = 0.05) -> pd.DataFrame:
    """Construct a synthetic OHLCV panel where the cross-sectional rank of
    ``close`` cleanly forecasts r_5d.

    For every date ``t`` we pick a per-symbol multiplier that ranks
    A > B > C > D, then set the next 5-day forward return to also rank
    A > B > C > D with the same monotone ordering. The trivial factor
    ``rank(close)`` should therefore produce a Spearman IC ≈ 1 against
    r_5d on this panel.
    """
    rng = np.random.default_rng(42)
    dates = _trading_days(n_days)
    symbols = ["A", "B", "C", "D"]

    # Per-symbol levels: distinct so cross-sectional ranks are stable per day.
    # We bake the rank ordering directly into close so ``rank(close)`` is
    # constant across days (== symbol rank) and so is r_5d.
    base_level = {"A": 400.0, "B": 300.0, "C": 200.0, "D": 100.0}

    rows: list[dict] = []
    for sym in symbols:
        # Add a tiny per-day jitter so close isn't perfectly constant
        # (which would zero out scipy's spearman correlation per day).
        jitter = rng.normal(0.0, 0.01, n_days).cumsum()
        close = base_level[sym] + jitter
        for d, c in zip(dates, close):
            rows.append(
                {
                    "date": d.date(),
                    "symbol": sym,
                    "open": float(c) * 0.999,
                    "high": float(c) * 1.005,
                    "low": float(c) * 0.995,
                    "close": float(c),
                    "volume": 1_000_000,
                }
            )
    df = pd.DataFrame(rows).set_index(["date", "symbol"]).sort_index()
    # Now overwrite close so that the actual realised forward returns
    # rank A > B > C > D each day. We do this by setting close[t+5] /
    # close[t] - 1 to a per-symbol target. Simpler approach: replace
    # close with a geometric series whose growth rate matches rank order.
    growth = {"A": 0.020, "B": 0.010, "C": 0.005, "D": -0.001}
    for sym in symbols:
        sym_idx = df.xs(sym, level="symbol", drop_level=False).index
        n = len(sym_idx)
        # A series whose pct_change(5) produces the per-symbol rate.
        # Daily rate g such that (1+g)^5 - 1 ≈ growth[sym].
        daily = (1.0 + growth[sym]) ** (1.0 / 5.0) - 1.0
        new_close = base_level[sym] * np.cumprod(np.full(n, 1.0 + daily))
        df.loc[sym_idx, "close"] = new_close
        df.loc[sym_idx, "open"] = new_close * 0.999
        df.loc[sym_idx, "high"] = new_close * 1.005
        df.loc[sym_idx, "low"] = new_close * 0.995
    return df


@pytest.fixture(autouse=True)
def _no_universe(monkeypatch):
    """Patch load_universe_panel so tests never touch SQLite."""
    from app.services import factor_backtest_service as svc

    async def _empty(_start, _end):
        return pd.Series(dtype=bool)

    monkeypatch.setattr(svc, "load_universe_panel", _empty)


# ---------------------------------------------------------------------------
# Core integration assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backtest_close_factor_produces_positive_ic():
    """A factor of 'close' should rank-predict next-period returns on a
    synthetic panel where higher close drives higher forward return."""
    panel = _build_panel(60, signal_strength=0.10)

    # The parser requires a top-level function call. ``rank(close)`` is the
    # cross-sectional rank — it preserves the monotone ordering of close
    # so the IC sign and magnitude are unchanged.
    result = await backtest_factor(
        "rank(close)",
        start=date(2024, 1, 2),
        end=date(2024, 12, 31),
        panel=panel,
    )

    assert isinstance(result, BacktestResult)
    assert result.fitness != FAILED_FITNESS
    assert result.n_obs > 0
    assert result.n_days > 0
    # Cross-sectional correlation between higher close and higher r_5d
    # should be unmistakably positive given how the panel was constructed.
    assert result.ic_5d > 0.5, f"expected strong IC, got {result.ic_5d}"
    assert result.rank_ic_5d > 0.5
    # Composite fitness uses positive weights, so it should be positive too.
    assert result.fitness > 0.0


@pytest.mark.asyncio
async def test_backtest_empty_panel_returns_failed():
    empty = pd.DataFrame()

    result = await backtest_factor(
        "rank(close)",
        start=date(2024, 1, 2),
        end=date(2024, 1, 31),
        panel=empty,
    )

    assert result.fitness == FAILED_FITNESS
    assert result.n_obs == 0
    assert math.isnan(result.ic_5d)
    assert result.return_curve == []


@pytest.mark.asyncio
async def test_backtest_constant_score_yields_near_zero_ic():
    """Constant factor → spearman_ic returns 0 per day → mean IC ≈ 0."""
    panel = _build_panel(40)

    # The seed-friendly way to express a constant: a literal column / 1
    # collapses to a constant only when the column itself is constant — so
    # use the AST directly with a numeric literal node.
    from core.factors import FactorNode

    # `add(0,0)` → constant 0 series across the panel.
    node = FactorNode("add", (0.0, 0.0))

    result = await backtest_factor(
        node,
        start=date(2024, 1, 2),
        end=date(2024, 12, 31),
        panel=panel,
    )

    # Either failed (no variance to score) or near-zero IC. We accept both.
    if result.fitness != FAILED_FITNESS:
        assert abs(result.ic_5d) < 0.05
    else:
        assert result.fitness == FAILED_FITNESS


# ---------------------------------------------------------------------------
# compute_metrics — direct (no async / no DB)
# ---------------------------------------------------------------------------


def test_compute_metrics_handles_all_nan_scores():
    panel = _build_panel(30)
    scores = pd.Series(np.nan, index=panel.index, name="factor")

    returns_panel = pd.DataFrame(
        {
            "r_1d": pd.Series(0.01, index=panel.index),
            "r_5d": pd.Series(0.05, index=panel.index),
            "r_20d": pd.Series(0.20, index=panel.index),
        }
    )

    out = compute_metrics(scores, returns_panel)

    assert out["failed"] is True


def test_compute_metrics_short_window_still_returns_dict():
    panel = _build_panel(8)
    scores = pd.Series(
        np.linspace(0.0, 1.0, len(panel.index)), index=panel.index, name="factor"
    )
    returns_panel = pd.DataFrame(
        {
            "r_1d": scores * 0.01,
            "r_5d": scores * 0.05,
            "r_20d": scores * 0.20,
        }
    )

    out = compute_metrics(scores, returns_panel)

    # Either reports a fitness or marks failed; either way it must return
    # a dict and not crash.
    assert isinstance(out, dict)
    assert "failed" in out
