"""Pull prices via yfinance + delegate to the pure-compute optimiser."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.services.network_utils import run_sync_with_retries
from core.portfolio_opt import SUPPORTED_MODES, optimise

logger = logging.getLogger(__name__)


def _download_blocking(tickers: list[str], lookback_days: int) -> pd.DataFrame:
    """yfinance bulk download → DataFrame of close prices.

    Uses period derived from `lookback_days` (defaults to ~1 year, 252
    trading days ≈ 365 calendar). yfinance accepts free-form period
    strings like `"1y"`, `"6mo"` — we round to the nearest sensible
    string rather than computing an exact start date.
    """
    import yfinance as yf

    if lookback_days <= 21:
        period = "1mo"
    elif lookback_days <= 63:
        period = "3mo"
    elif lookback_days <= 126:
        period = "6mo"
    elif lookback_days <= 252:
        period = "1y"
    elif lookback_days <= 504:
        period = "2y"
    else:
        period = "5y"

    frame = yf.download(
        tickers=" ".join(tickers),
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    if frame is None or getattr(frame, "empty", True):
        return pd.DataFrame()

    closes: dict[str, pd.Series] = {}
    for sym in tickers:
        try:
            if sym in getattr(frame.columns, "levels", [[]])[0]:
                sub = frame[sym]
            else:
                sub = frame
            if "Close" not in sub.columns:
                continue
            closes[sym] = sub["Close"].dropna()
        except Exception as exc:  # noqa: BLE001
            logger.debug("portfolio_opt: close parse failed for %s: %s", sym, exc)
            continue

    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(closes)


async def run_optimization(
    *,
    tickers: list[str],
    lookback_days: int = 252,
    mode: str = "max_sharpe",
    target_return: float | None = None,
    risk_free_rate: float = 0.04,
    backend: str = "pyportfolioopt",
) -> dict[str, Any]:
    """High-level entry point.

    Raises:
        ValueError on bad inputs / optimisation failure.
        RuntimeError when yfinance returns no data, or when skfolio
        backend is requested but the package isn't installed.
    """
    if not tickers:
        raise ValueError("tickers is required")
    if len(tickers) < 2:
        raise ValueError("at least 2 tickers required")
    if backend not in {"pyportfolioopt", "skfolio"}:
        raise ValueError(f"backend must be 'pyportfolioopt' or 'skfolio', got {backend!r}")
    if backend == "pyportfolioopt" and mode not in SUPPORTED_MODES:
        raise ValueError(
            f"PyPortfolioOpt mode must be one of {SUPPORTED_MODES!r}, got {mode!r}"
        )
    if backend == "skfolio" and mode not in {"max_sharpe", "mean_risk", "hrp"}:
        raise ValueError(
            f"skfolio mode must be one of mean_risk/max_sharpe/hrp, got {mode!r}"
        )

    normalized = [str(t).strip().upper() for t in tickers if str(t).strip()]
    if len(normalized) < 2:
        raise ValueError("at least 2 valid tickers required after normalisation")

    prices = await run_sync_with_retries(_download_blocking, normalized, lookback_days)
    if prices.empty:
        raise RuntimeError("yfinance returned no price data for the requested tickers")

    if backend == "skfolio":
        from core.portfolio_opt.skfolio_adapter import optimise as sk_optimise
        sk_mode = "hrp" if mode == "hrp" else "mean_risk"
        sk_result = await run_sync_with_retries(
            sk_optimise, prices, mode=sk_mode, risk_free_rate=risk_free_rate,
        )
        return {
            "tickers": normalized,
            "lookback_days": lookback_days,
            "mode": mode,
            "target_return": target_return,
            "risk_free_rate": risk_free_rate,
            "weights": sk_result.weights,
            "expected_return": sk_result.expected_return,
            "expected_volatility": sk_result.expected_volatility,
            "sharpe_ratio": sk_result.sharpe_ratio,
            "backend": "skfolio",
            "as_of": datetime.now(timezone.utc),
        }

    result = optimise(
        prices,
        mode=mode,  # type: ignore[arg-type]
        target_return=target_return,
        risk_free_rate=risk_free_rate,
    )

    return {
        "tickers": normalized,
        "lookback_days": lookback_days,
        "mode": mode,
        "target_return": target_return,
        "risk_free_rate": risk_free_rate,
        "weights": result.weights,
        "expected_return": result.expected_return,
        "expected_volatility": result.expected_volatility,
        "sharpe_ratio": result.sharpe_ratio,
        "backend": "pyportfolioopt",
        "as_of": datetime.now(timezone.utc),
    }
