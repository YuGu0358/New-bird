"""Parametric + historical VaR / CVaR."""
from __future__ import annotations

import math

import pytest

from core.quantlib.risk import historical_var, parametric_var


def test_parametric_var_one_day_normal() -> None:
    """For mean=0, sigma=0.01, 1-day horizon, 95% conf:
    VaR = 1.645 * 0.01 * sqrt(1) ≈ 0.01645 per unit notional.
    Notional 1,000,000 → VaR ≈ 16,449."""
    result = parametric_var(
        notional=1_000_000.0,
        mean_return=0.0,
        std_return=0.01,
        confidence=0.95,
        horizon_days=1,
    )
    assert result.var == pytest.approx(16449, rel=0.05)
    assert result.cvar > result.var          # CVaR is conservative


def test_parametric_var_scales_with_horizon() -> None:
    """VaR should scale with sqrt(horizon)."""
    one_day = parametric_var(
        notional=1_000_000.0, mean_return=0.0, std_return=0.01,
        confidence=0.95, horizon_days=1,
    )
    ten_day = parametric_var(
        notional=1_000_000.0, mean_return=0.0, std_return=0.01,
        confidence=0.95, horizon_days=10,
    )
    ratio = ten_day.var / one_day.var
    assert ratio == pytest.approx(math.sqrt(10), rel=0.02)


def test_historical_var_matches_quantile() -> None:
    """Returns from -0.10 to +0.09 step 0.002 (100 points).
    5th percentile ≈ -0.090; VaR ≈ 0.090 * 1,000,000 = 90,000."""
    returns = [(-0.10 + i * 0.002) for i in range(100)]
    result = historical_var(
        notional=1_000_000.0,
        returns=returns,
        confidence=0.95,
        horizon_days=1,
    )
    assert result.var == pytest.approx(90_000, rel=0.05)


def test_historical_var_rejects_too_few_returns() -> None:
    with pytest.raises(ValueError):
        historical_var(notional=1.0, returns=[0.01], confidence=0.95, horizon_days=1)


def test_parametric_var_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        parametric_var(notional=1.0, mean_return=0, std_return=0.01, confidence=1.5, horizon_days=1)
