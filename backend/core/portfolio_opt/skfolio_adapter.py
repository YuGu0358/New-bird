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
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import pandas as pd  # used only for the annotation; runtime gets it lazily


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

    # Defensive attribute discovery — skfolio's Portfolio API has shifted
    # across releases (`portfolio.assets` + `portfolio.weights` array vs
    # `portfolio.weights` dict vs `model.weights_`). Try the common shapes
    # in order and fall back to `model.weights_` zipped with the input
    # column names. Raises with a clear error if none works so the user
    # gets a fixable hint rather than an opaque AttributeError.
    weights: dict[str, float] = {}
    cols = list(returns.columns)
    if hasattr(portfolio, "weights") and hasattr(portfolio, "assets"):
        try:
            for name, w in zip(portfolio.assets, portfolio.weights):
                wf = float(w)
                if abs(wf) > 1e-6:
                    weights[str(name)] = wf
        except Exception:
            weights = {}
    if not weights and hasattr(portfolio, "weights"):
        # weights might be a dict on some versions
        w_obj = portfolio.weights
        if isinstance(w_obj, dict):
            weights = {str(k): float(v) for k, v in w_obj.items() if abs(float(v)) > 1e-6}
    if not weights and hasattr(model, "weights_"):
        try:
            for name, w in zip(cols, model.weights_):
                wf = float(w)
                if abs(wf) > 1e-6:
                    weights[str(name)] = wf
        except Exception:
            pass
    if not weights:
        raise RuntimeError(
            "skfolio fit succeeded but weights could not be extracted — "
            "the installed skfolio version may have an incompatible Portfolio API."
        )

    # skfolio.Portfolio exposes annualized stats — be tolerant about which
    # attribute names are present; log when we fall back so a regression in
    # skfolio internals doesn't silently zero out our forecasts.
    ann_return = 0.0
    ann_vol = 0.0
    sharpe = 0.0
    try:
        if hasattr(portfolio, "mean"):
            ann_return = float(portfolio.mean) * 252
        if hasattr(portfolio, "standard_deviation"):
            ann_vol = float(portfolio.standard_deviation) * (252 ** 0.5)
        sharpe = (ann_return - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "skfolio stats extraction failed (%s); returning zeros", exc
        )

    return SkfolioResult(
        weights=weights,
        expected_return=ann_return,
        expected_volatility=ann_vol,
        sharpe_ratio=sharpe,
    )
