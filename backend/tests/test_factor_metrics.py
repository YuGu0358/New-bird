"""Unit tests for the pure metric helpers in core.factors.metrics.

No DB, no network — these exercise the math only.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core.factors.metrics import (
    calmar,
    max_drawdown,
    pearson_ic,
    sharpe,
    sortino,
    spearman_ic,
    turnover,
)


# ---------------------------------------------------------------------------
# spearman_ic
# ---------------------------------------------------------------------------


def test_spearman_ic_perfect_monotonic_pair():
    # Arrange — returns is a strictly monotone function of scores.
    scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    returns = scores * 2.0

    # Act
    rho = spearman_ic(scores, returns)

    # Assert — Spearman is rank-based so any monotone map yields exactly 1.
    assert rho == pytest.approx(1.0)


def test_spearman_ic_constant_scores_returns_zero():
    scores = np.array([0.5, 0.5, 0.5, 0.5, 0.5])
    returns = np.array([0.1, -0.2, 0.05, 0.0, 0.3])

    rho = spearman_ic(scores, returns)

    # std=0 path → 0 (not NaN), so GP search ranks constant factors as worst.
    assert rho == pytest.approx(0.0)


def test_spearman_ic_drops_nan_rows():
    scores = np.array([1.0, np.nan, 3.0, 4.0, 5.0])
    returns = np.array([2.0, 4.0, np.nan, 8.0, 10.0])

    rho = spearman_ic(scores, returns)

    # Surviving pairs (1,2), (4,8), (5,10) → still monotone.
    assert rho == pytest.approx(1.0)


def test_spearman_ic_too_few_points_is_nan():
    rho = spearman_ic(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
    assert math.isnan(rho)


def test_pearson_ic_constant_returns_zero():
    scores = np.array([1.0, 2.0, 3.0, 4.0])
    returns = np.array([5.0, 5.0, 5.0, 5.0])

    assert pearson_ic(scores, returns) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# sharpe / sortino
# ---------------------------------------------------------------------------


def test_sharpe_matches_manual_computation():
    # Arrange
    rets = np.array([0.01, -0.005, 0.02, 0.0, 0.015, -0.01, 0.005])

    # Act
    s = sharpe(rets)

    # Assert — manual: (mean / std_ddof1) * sqrt(252)
    mean = rets.mean()
    std = rets.std(ddof=1)
    expected = (mean / std) * math.sqrt(252)
    assert s == pytest.approx(expected)


def test_sharpe_zero_std_is_nan():
    s = sharpe(np.array([0.01, 0.01, 0.01]))
    assert math.isnan(s)


def test_sortino_uses_downside_only_std():
    rets = np.array([0.05, -0.02, 0.04, -0.03, 0.01])
    s = sortino(rets)
    downside = rets[rets < 0]
    expected = (rets.mean() / downside.std(ddof=1)) * math.sqrt(252)
    assert s == pytest.approx(expected)


# ---------------------------------------------------------------------------
# max_drawdown / calmar
# ---------------------------------------------------------------------------


def test_max_drawdown_simple_case():
    # Peak 1.1 → trough 0.9 → drawdown = (1.1 - 0.9) / 1.1 ≈ 0.1818
    equity = [1.0, 1.1, 0.9, 1.05]

    dd = max_drawdown(equity)

    assert dd == pytest.approx(0.2 / 1.1, abs=1e-6)
    assert dd == pytest.approx(0.1818, abs=1e-3)


def test_max_drawdown_monotone_curve_is_zero():
    equity = [1.0, 1.05, 1.1, 1.2]
    assert max_drawdown(equity) == pytest.approx(0.0)


def test_calmar_positive_when_profitable_with_drawdown():
    rets = np.array([0.02, -0.01, 0.03, -0.005, 0.015, 0.01])
    c = calmar(rets)
    assert math.isfinite(c)
    assert c > 0.0


# ---------------------------------------------------------------------------
# turnover
# ---------------------------------------------------------------------------


def test_turnover_one_swap_in_three_basket():
    """{A,B,C} → {A,B,D}: one symbol swapped on a size-3 basket → 1/3."""
    t = turnover([{"A", "B", "C"}, {"A", "B", "D"}])
    assert t == pytest.approx(1.0 / 3.0)


def test_turnover_identical_baskets_zero():
    t = turnover([{"A", "B", "C"}, {"A", "B", "C"}, {"A", "B", "C"}])
    assert t == pytest.approx(0.0)


def test_turnover_full_replacement_one():
    t = turnover([{"A", "B"}, {"C", "D"}])
    assert t == pytest.approx(1.0)


def test_turnover_too_few_baskets_nan():
    assert math.isnan(turnover([{"A", "B"}]))
    assert math.isnan(turnover([]))


def test_turnover_mean_over_multiple_transitions():
    # First transition is 0 (no change), second is 1/3 → mean = 1/6.
    t = turnover([{"A", "B", "C"}, {"A", "B", "C"}, {"A", "B", "D"}])
    assert t == pytest.approx(1.0 / 6.0)
