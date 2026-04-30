"""skfolio backend for portfolio optimisation — borrowed from FinceptTerminal.

Optional: only used when ``backend="skfolio"`` is requested. Lazy-imports
the package so the rest of NewBird keeps working even when skfolio
isn't installed. skfolio offers HRP / NCO / Mean-Risk / robust covariance
models that PyPortfolioOpt doesn't expose; we surface a small subset
here and let users pull the rest by installing skfolio themselves.

Install: ``pip install skfolio`` (note: pulls scikit-learn, cvxpy).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd


SkfolioMode = Literal["mean_risk", "hrp"]


@dataclass(frozen=True)
class SkfolioResult:
    """Same shape as core.portfolio_opt.optimizer.OptimizationResult."""

    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    backend: str = "skfolio"


def is_available() -> bool:
    """True when skfolio can be imported."""
    try:
        import skfolio  # noqa: F401
        return True
    except Exception:
        return False


def optimise(
    prices: pd.DataFrame,
    *,
    mode: SkfolioMode = "mean_risk",
    risk_free_rate: float = 0.04,
) -> SkfolioResult:
    """Run a skfolio optimisation.

    Modes:
    - ``mean_risk``: skfolio.optimization.MeanRisk (~ Markowitz with
      modern numerics). Maximises Sharpe by default.
    - ``hrp``: Hierarchical Risk Parity (López de Prado). No expected
      return / Sharpe forecast — those fields are returned as 0.

    Raises:
        RuntimeError when skfolio isn't installed.
        ValueError on bad input.
    """
    if prices is None or prices.empty:
        raise ValueError("prices DataFrame is empty")

    try:
        from skfolio.optimization import MeanRisk, HierarchicalRiskParity
        from skfolio.preprocessing import prices_to_returns
    except Exception as exc:  # pragma: no cover — environment-dependent
        raise RuntimeError(
            "skfolio not installed. Run `pip install skfolio` to enable this backend."
        ) from exc

    returns = prices_to_returns(prices)

    if mode == "mean_risk":
        model = MeanRisk(risk_free_rate=risk_free_rate)
    elif mode == "hrp":
        model = HierarchicalRiskParity()
    else:
        raise ValueError(f"unknown skfolio mode {mode!r}")

    portfolio = model.fit_predict(returns)

    weights = {
        str(name): float(w)
        for name, w in zip(portfolio.assets, portfolio.weights)
        if abs(float(w)) > 1e-6
    }

    # skfolio.Portfolio exposes annualized stats.
    try:
        ann_return = float(portfolio.mean) * 252
        ann_vol = float(portfolio.standard_deviation) * (252 ** 0.5)
        sharpe = (ann_return - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0
    except Exception:
        ann_return = 0.0
        ann_vol = 0.0
        sharpe = 0.0

    return SkfolioResult(
        weights=weights,
        expected_return=ann_return,
        expected_volatility=ann_vol,
        sharpe_ratio=sharpe,
    )
