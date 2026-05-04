"""Performance metric formulas — known inputs only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.backtest.metrics import (
    cagr,
    compute_metrics,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    total_return,
    win_rate,
)


def _curve(values: list[float]) -> list[tuple[datetime, float]]:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [(base + timedelta(days=i), v) for i, v in enumerate(values)]


def test_total_return_pct() -> None:
    curve = _curve([100.0, 110.0, 121.0])
    assert round(total_return(curve), 4) == 0.21


def test_total_return_empty() -> None:
    assert total_return([]) == 0.0


def test_max_drawdown_simple() -> None:
    curve = _curve([100.0, 120.0, 90.0, 110.0])
    # peak 120 -> trough 90 -> drawdown = (90 - 120) / 120 = -0.25
    assert round(max_drawdown(curve), 4) == -0.25


def test_max_drawdown_monotonic_returns_zero() -> None:
    curve = _curve([100.0, 105.0, 110.0])
    assert max_drawdown(curve) == 0.0


def test_sharpe_ratio_positive_for_steady_growth() -> None:
    curve = _curve([100.0 * (1.001) ** i for i in range(252)])
    sr = sharpe_ratio(curve, periods_per_year=252)
    assert sr > 5.0  # nearly deterministic 0.1% daily growth


def test_sortino_handles_no_negatives() -> None:
    curve = _curve([100.0, 101.0, 102.0])
    # No downside → infinity in pure math; we cap at a large number.
    s = sortino_ratio(curve, periods_per_year=252)
    assert s > 0


def test_cagr_two_year_doubling() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    curve = [(base, 100.0), (base + timedelta(days=365 * 2), 200.0)]
    # CAGR ≈ 2^(1/2) - 1 ≈ 0.4142
    assert round(cagr(curve), 4) == pytest.approx(0.4142, abs=1e-3)


def test_win_rate_and_profit_factor() -> None:
    pnl_per_trade = [100.0, -50.0, 200.0, -100.0, 50.0]
    assert round(win_rate(pnl_per_trade), 4) == 0.6
    # gross profit 350, gross loss 150 -> pf = 350/150 ≈ 2.3333
    assert round(profit_factor(pnl_per_trade), 4) == 2.3333


def test_compute_metrics_returns_dict() -> None:
    curve = _curve([100.0, 105.0, 102.0, 110.0])
    pnl = [5.0, -3.0, 8.0]
    metrics = compute_metrics(curve, pnl_per_trade=pnl, periods_per_year=252)
    for key in ("total_return", "cagr", "sharpe", "sortino", "max_drawdown", "calmar", "win_rate", "profit_factor"):
        assert key in metrics
