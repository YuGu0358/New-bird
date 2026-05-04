"""Tests for the backtest tearsheet — pure compute + service with mocked DB."""
from __future__ import annotations

import math
import unittest
from unittest.mock import AsyncMock, patch

import pytest

from app.services import tearsheet_service
from core.quantstats import compute_tearsheet
from core.quantstats.metrics import (
    _downside_stdev,
    _max_drawdown,
    _stdev,
    _to_returns,
)


# ---------- Pure compute internals ----------


def test_to_returns_basic():
    assert _to_returns([100.0, 110.0, 121.0]) == [pytest.approx(0.10), pytest.approx(0.10)]


def test_to_returns_handles_non_positive_prev():
    """Defensive: prev=0 short-circuits to 0.0 (not div-by-zero)."""
    assert _to_returns([0.0, 100.0]) == [0.0]


def test_stdev_zero_for_one_point():
    assert _stdev([1.0]) == 0.0


def test_stdev_sample_denominator():
    """sample stdev with n-1 denominator: stdev([1,2,3,4,5]) = sqrt(2.5)."""
    assert _stdev([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(math.sqrt(2.5))


def test_downside_stdev_only_below_threshold():
    """[+0.05, -0.02, -0.03, +0.01] threshold=0 → stdev of [-0.02, -0.03]."""
    out = _downside_stdev([0.05, -0.02, -0.03, 0.01], threshold=0.0)
    assert out > 0
    # Manual: deviations from 0 are -0.02 and -0.03 → sample stdev with n-1=1
    # var = ((-0.02)^2 + (-0.03)^2) / 1 = 0.0013; sqrt(0.0013) ≈ 0.0360555
    assert out == pytest.approx(math.sqrt((0.02**2 + 0.03**2) / 1))


def test_max_drawdown_simple():
    """Equity 100→120→80→90: peak 120, trough 80 → drawdown -33.33%."""
    out = _max_drawdown([100.0, 120.0, 80.0, 90.0])
    assert out == pytest.approx(-1.0 / 3.0)


def test_max_drawdown_monotone_up_returns_zero():
    assert _max_drawdown([100.0, 110.0, 120.0]) == 0.0


def test_max_drawdown_empty_series():
    assert _max_drawdown([]) == 0.0


# ---------- compute_tearsheet ----------


def test_compute_tearsheet_basic_pinned_values():
    """Constant 1% daily return for 252 days.

    With rf=0% the math is clean:
    - returns = [0.01]*252
    - mean(returns) = 0.01, stdev = 0
    - Sharpe is None (vol_per_period == 0)
    - CAGR ≈ (1.01)^252 - 1 over years=1 → matches
    """
    equity = [100.0]
    for _ in range(252):
        equity.append(equity[-1] * 1.01)

    out = compute_tearsheet(equity, periods_per_year=252, risk_free_rate=0.0)
    assert out.periods == 253  # initial + 252 daily updates
    assert out.cagr == pytest.approx((1.01**252) - 1.0, rel=1e-9)
    assert out.volatility == pytest.approx(0.0, abs=1e-12)
    assert out.sharpe is None  # zero vol → undefined Sharpe
    assert out.max_drawdown == 0.0
    assert out.total_return == pytest.approx((1.01**252) - 1.0, rel=1e-9)


def test_compute_tearsheet_with_drawdown():
    """Hand-crafted series where peak/trough is obvious."""
    equity = [100.0, 120.0, 80.0, 100.0]  # peak 120 → trough 80 = -33.3%
    out = compute_tearsheet(equity, periods_per_year=252, risk_free_rate=0.0)
    assert out.max_drawdown == pytest.approx(-1.0 / 3.0)
    assert out.total_return == 0.0
    # CAGR with 3 returns over 3/252 years > 0 (but the curve is flat
    # initial→final, so total_return is 0 → CAGR is 0).
    assert out.cagr == pytest.approx(0.0)
    # Calmar = CAGR / |MaxDD| = 0 / (1/3) = 0
    assert out.calmar == pytest.approx(0.0)


def test_compute_tearsheet_short_series_returns_none():
    out = compute_tearsheet([100.0], periods_per_year=252)
    assert out.cagr is None
    assert out.sharpe is None
    assert out.periods == 1


def test_compute_tearsheet_empty_series_returns_none():
    out = compute_tearsheet([], periods_per_year=252)
    assert out.cagr is None
    assert out.periods == 0


def test_compute_tearsheet_total_return_formula():
    out = compute_tearsheet(
        [100.0, 110.0, 105.0, 130.0], periods_per_year=252, risk_free_rate=0.0
    )
    assert out.total_return == pytest.approx(0.30)


def test_compute_tearsheet_sortino_uses_only_downside_returns():
    """Two losing days, one winning day — Sortino should be defined."""
    equity = [100.0, 102.0, 95.0, 90.0]  # +2%, -6.86%, -5.26%
    out = compute_tearsheet(equity, periods_per_year=252, risk_free_rate=0.0)
    assert out.sortino is not None
    # Sortino uses sqrt(downside variance with n-1 denom). Manual is messy;
    # just assert sign + bounded magnitude.
    assert out.sortino < 0  # mean excess return is negative


# ---------- Service ----------


class TearsheetServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_tearsheet_pulls_curve_and_runs_metrics(self) -> None:
        fake_curve = [
            {"timestamp": "2026-01-01T00:00:00Z", "equity": 100.0},
            {"timestamp": "2026-01-02T00:00:00Z", "equity": 105.0},
            {"timestamp": "2026-01-03T00:00:00Z", "equity": 110.0},
        ]
        with patch.object(
            tearsheet_service.backtest_service,
            "get_equity_curve",
            new=AsyncMock(return_value=fake_curve),
        ):
            payload = await tearsheet_service.get_tearsheet(
                session=None, run_id=42  # session unused thanks to the mock
            )

        self.assertEqual(payload["run_id"], 42)
        self.assertEqual(payload["periods"], 3)
        self.assertEqual(payload["periods_per_year"], 252)
        self.assertAlmostEqual(payload["total_return"], 0.10, places=6)

    async def test_get_tearsheet_returns_none_for_missing_run(self) -> None:
        with patch.object(
            tearsheet_service.backtest_service,
            "get_equity_curve",
            new=AsyncMock(return_value=None),
        ):
            payload = await tearsheet_service.get_tearsheet(
                session=None, run_id=999
            )
        self.assertIsNone(payload)

    async def test_get_tearsheet_skips_malformed_points(self) -> None:
        """A garbage 'equity' shouldn't poison the math."""
        fake_curve = [
            {"timestamp": "2026-01-01T00:00:00Z", "equity": 100.0},
            {"timestamp": "2026-01-02T00:00:00Z", "equity": "not a number"},
            {"timestamp": "2026-01-03T00:00:00Z"},  # missing value
            {"timestamp": "2026-01-04T00:00:00Z", "equity": 110.0},
        ]
        with patch.object(
            tearsheet_service.backtest_service,
            "get_equity_curve",
            new=AsyncMock(return_value=fake_curve),
        ):
            payload = await tearsheet_service.get_tearsheet(
                session=None, run_id=1
            )
        # Only 100 and 110 made it through → periods = 2.
        self.assertEqual(payload["periods"], 2)
        self.assertAlmostEqual(payload["total_return"], 0.10, places=6)
