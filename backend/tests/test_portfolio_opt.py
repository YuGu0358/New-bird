"""Portfolio optimisation tests — pure compute + service with mocked yfinance."""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.services import portfolio_opt_service
from core.portfolio_opt import SUPPORTED_MODES, optimise


def _synthetic_prices(seed: int = 42, n_days: int = 504, n_tickers: int = 4) -> pd.DataFrame:
    """Deterministic price series — log-Brownian with distinct drifts."""
    rng = np.random.default_rng(seed)
    # Drifts chosen so realised mu cleanly exceeds the 4% rf rate after
    # noise — required for max_sharpe to be feasible on this seed.
    drifts = np.linspace(0.0008, 0.0020, n_tickers)
    sigmas = np.linspace(0.01, 0.025, n_tickers)
    cols = [f"T{i}" for i in range(n_tickers)]
    starts = np.full(n_tickers, 100.0)
    log_prices = np.zeros((n_days, n_tickers))
    log_prices[0] = np.log(starts)
    for t in range(1, n_days):
        shocks = rng.standard_normal(n_tickers) * sigmas
        log_prices[t] = log_prices[t - 1] + drifts + shocks
    prices = pd.DataFrame(np.exp(log_prices), columns=cols)
    prices.index = pd.date_range("2024-01-01", periods=n_days, freq="B")
    return prices


# ---------- Pure compute ----------


def test_optimise_max_sharpe_returns_normalised_weights():
    prices = _synthetic_prices()
    result = optimise(prices, mode="max_sharpe", risk_free_rate=0.04)
    assert abs(sum(result.weights.values()) - 1.0) < 1e-6
    for w in result.weights.values():
        assert 0.0 - 1e-9 <= w <= 1.0 + 1e-9


def test_optimise_min_volatility_returns_lower_vol_than_max_sharpe():
    prices = _synthetic_prices()
    sharpe_result = optimise(prices, mode="max_sharpe", risk_free_rate=0.04)
    minvol_result = optimise(prices, mode="min_volatility")
    # min_volatility should not increase vol vs max_sharpe.
    assert minvol_result.expected_volatility <= sharpe_result.expected_volatility + 1e-6


def test_optimise_efficient_return_hits_target_within_tolerance():
    prices = _synthetic_prices()
    target = 0.10  # 10% annual
    result = optimise(prices, mode="efficient_return", target_return=target)
    # Allow 1pp tolerance — solver doesn't have to hit it exactly.
    assert abs(result.expected_return - target) < 0.02


def test_optimise_rejects_unknown_mode():
    prices = _synthetic_prices()
    with pytest.raises(ValueError, match="mode must be one of"):
        optimise(prices, mode="nonsense")  # type: ignore[arg-type]


def test_optimise_rejects_empty_frame():
    with pytest.raises(ValueError, match="prices DataFrame is empty"):
        optimise(pd.DataFrame())


def test_optimise_rejects_single_ticker():
    prices = _synthetic_prices(n_tickers=1)
    with pytest.raises(ValueError, match="at least 2 tickers"):
        optimise(prices)


def test_optimise_efficient_return_requires_target():
    prices = _synthetic_prices()
    with pytest.raises(ValueError, match="target_return is required"):
        optimise(prices, mode="efficient_return")


def test_supported_modes_constant():
    assert set(SUPPORTED_MODES) == {"max_sharpe", "min_volatility", "efficient_return"}


# ---------- Service ----------


class PortfolioOptServiceTests(unittest.IsolatedAsyncioTestCase):

    async def test_run_optimization_rejects_short_ticker_list(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 2 tickers"):
            await portfolio_opt_service.run_optimization(tickers=["AAPL"])

    async def test_run_optimization_rejects_unknown_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "mode must be one of"):
            await portfolio_opt_service.run_optimization(
                tickers=["AAPL", "MSFT"], mode="nonsense"
            )

    async def test_run_optimization_normalizes_tickers(self) -> None:
        # Even with mocked download, the upstream call should see uppercase.
        captured: dict[str, Any] = {}

        def fake_download(tickers: list[str], lookback_days: int) -> pd.DataFrame:
            captured["tickers"] = tickers
            return _synthetic_prices()

        with patch.object(
            portfolio_opt_service,
            "_download_blocking",
            side_effect=fake_download,
        ):
            payload = await portfolio_opt_service.run_optimization(
                tickers=[" aapl ", "MSFT", "  goog"]
            )
        # Synthetic frame has columns T0..T3, but we still verify the
        # service forwarded uppercased ticker list.
        self.assertEqual(captured["tickers"], ["AAPL", "MSFT", "GOOG"])
        self.assertEqual(payload["mode"], "max_sharpe")
        self.assertEqual(set(payload["weights"]), {"T0", "T1", "T2", "T3"})

    async def test_run_optimization_raises_runtime_error_on_empty_frame(self) -> None:
        with patch.object(
            portfolio_opt_service,
            "_download_blocking",
            side_effect=lambda t, d: pd.DataFrame(),
        ):
            with self.assertRaisesRegex(RuntimeError, "no price data"):
                await portfolio_opt_service.run_optimization(
                    tickers=["AAPL", "MSFT"]
                )

    async def test_run_optimization_full_payload_shape(self) -> None:
        with patch.object(
            portfolio_opt_service,
            "_download_blocking",
            side_effect=lambda t, d: _synthetic_prices(),
        ):
            payload = await portfolio_opt_service.run_optimization(
                tickers=["AAPL", "MSFT", "GOOG", "NVDA"],
                lookback_days=252,
                mode="max_sharpe",
                risk_free_rate=0.04,
            )
        for key in (
            "tickers",
            "lookback_days",
            "mode",
            "weights",
            "expected_return",
            "expected_volatility",
            "sharpe_ratio",
            "as_of",
        ):
            self.assertIn(key, payload)
        self.assertAlmostEqual(sum(payload["weights"].values()), 1.0, places=5)
