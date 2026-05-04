"""Mean-variance portfolio optimisation — pure compute on a price DataFrame.

Wraps PyPortfolioOpt's EfficientFrontier so the service layer doesn't
touch the library directly. Three convenience modes:

- `max_sharpe`        : maximise the Sharpe ratio at the given rf
- `min_volatility`    : minimise portfolio volatility
- `efficient_return`  : minimise volatility subject to a target return

Inputs:
    prices : pandas.DataFrame, columns = tickers, index = dates,
             values = adjusted closes (or any price level — what matters
             is that returns are computable from differences). Missing
             cells are forward-filled inside this module.

Returns OptimizationResult with weights, expected return, expected
volatility, and Sharpe ratio for the chosen weights.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from pypfopt import EfficientFrontier, expected_returns, risk_models

logger = logging.getLogger(__name__)


ModeLiteral = Literal["max_sharpe", "min_volatility", "efficient_return"]
SUPPORTED_MODES: tuple[str, ...] = ("max_sharpe", "min_volatility", "efficient_return")


@dataclass
class OptimizationResult:
    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float


def optimise(
    prices: pd.DataFrame,
    *,
    mode: ModeLiteral = "max_sharpe",
    target_return: float | None = None,
    risk_free_rate: float = 0.04,
    weight_bounds: tuple[float, float] = (0.0, 1.0),
) -> OptimizationResult:
    """Run mean-variance optimisation on a price frame.

    Raises:
        ValueError on empty frame, fewer than 2 tickers, unknown mode,
        missing target_return for efficient_return, or solver failure.
    """
    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"mode must be one of {SUPPORTED_MODES!r}, got {mode!r}"
        )
    if prices is None or prices.empty:
        raise ValueError("prices DataFrame is empty")
    if len(prices.columns) < 2:
        raise ValueError("at least 2 tickers required for optimisation")
    if mode == "efficient_return" and target_return is None:
        raise ValueError("target_return is required for mode='efficient_return'")

    # Forward-fill missing cells so a single missing day doesn't trash
    # the cov matrix. Drop any column that's fully empty.
    cleaned = prices.ffill().dropna(axis=1, how="all").dropna(axis=0, how="any")
    if cleaned.shape[0] < 2:
        raise ValueError(
            "not enough rows after cleaning — need at least 2 price observations"
        )
    if cleaned.shape[1] < 2:
        raise ValueError(
            "not enough tickers after cleaning — at least 2 must have valid data"
        )

    mu = expected_returns.mean_historical_return(cleaned, frequency=252)
    cov = risk_models.sample_cov(cleaned, frequency=252)

    try:
        ef = EfficientFrontier(mu, cov, weight_bounds=weight_bounds, solver="SCS")
        if mode == "max_sharpe":
            ef.max_sharpe(risk_free_rate=risk_free_rate)
        elif mode == "min_volatility":
            ef.min_volatility()
        else:  # efficient_return
            ef.efficient_return(target_return=target_return, market_neutral=False)
    except Exception as exc:  # noqa: BLE001
        # Singular cov, infeasible target, or solver convergence failure.
        raise ValueError(f"optimisation failed: {exc}") from exc

    cleaned_weights = ef.clean_weights()
    perf = ef.portfolio_performance(
        verbose=False, risk_free_rate=risk_free_rate
    )
    expected_ret, expected_vol, sharpe = perf
    return OptimizationResult(
        weights={str(k): float(v) for k, v in cleaned_weights.items()},
        expected_return=float(expected_ret),
        expected_volatility=float(expected_vol),
        sharpe_ratio=float(sharpe),
    )
