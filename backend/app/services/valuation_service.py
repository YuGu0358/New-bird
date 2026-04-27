"""Valuation service — DCF + PE-channel.

The DCF endpoint takes user-supplied inputs (assumption tabs), so the service
is mostly a thin call into the engine. The PE-channel endpoint pulls 10 years
of price history + TTM EPS from yfinance.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.network_utils import run_sync_with_retries
from core.valuation import (
    DCFInputs,
    PEChannelOutput,
    compute_pe_channel,
    run_dcf,
)

logger = logging.getLogger(__name__)

_PE_CACHE_TTL = timedelta(hours=12)
_pe_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# DCF
# ---------------------------------------------------------------------------


def compute_dcf(
    *,
    fcfe0: float,
    growth_stage1: float,
    growth_terminal: float,
    discount_rate: float,
    years_stage1: int = 7,
    shares_out: float | None = None,
) -> dict[str, Any]:
    inputs = DCFInputs(
        fcfe0=fcfe0,
        growth_stage1=growth_stage1,
        growth_terminal=growth_terminal,
        discount_rate=discount_rate,
        years_stage1=years_stage1,
        shares_out=shares_out,
    )
    result = run_dcf(inputs)
    return {
        "inputs": asdict(inputs),
        "fair_value_per_share": result.fair_value_per_share,
        "fair_low": result.fair_low,
        "fair_high": result.fair_high,
        "breakdown": result.breakdown,
        "grid": list(result.grid),
        "generated_at": datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------------------
# PE channel
# ---------------------------------------------------------------------------


def _pe_inputs_blocking(ticker: str, lookback_years: int) -> dict[str, Any] | None:
    import yfinance as yf

    t = yf.Ticker(ticker)
    history = t.history(period=f"{lookback_years}y", auto_adjust=False)
    if history.empty:
        return None
    prices = [float(p) for p in history["Close"].dropna().tolist()]

    eps_ttm: float | None = None
    try:
        info = t.info or {}
        eps_ttm = float(info.get("trailingEps") or 0) or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("yfinance info(%s) failed: %s", ticker, exc)

    if eps_ttm is None:
        try:
            financials = t.financials
            if not financials.empty and "Diluted EPS" in financials.index:
                row = financials.loc["Diluted EPS"]
                if len(row) >= 4:
                    eps_ttm = float(row.iloc[:4].sum())
                else:
                    eps_ttm = float(row.iloc[0])
        except Exception as exc:  # noqa: BLE001
            logger.debug("yfinance financials(%s) failed: %s", ticker, exc)

    current_price: float | None = None
    try:
        fast = t.fast_info
        if fast.last_price:
            current_price = float(fast.last_price)
    except Exception:  # noqa: BLE001
        current_price = prices[-1] if prices else None

    return {"prices": prices, "eps_ttm": eps_ttm, "current_price": current_price}


async def fetch_pe_channel(
    ticker: str,
    *,
    lookback_years: int = 10,
    cagr: float = 0.07,
) -> dict[str, Any]:
    """Pull price + EPS from yfinance and compute the PE channel."""
    normalized = ticker.upper()
    cached = _pe_cache.get(normalized)
    now = datetime.now(timezone.utc)
    if cached and now - cached[0] <= _PE_CACHE_TTL:
        return cached[1]

    inputs = await run_sync_with_retries(_pe_inputs_blocking, normalized, lookback_years)
    if not inputs:
        empty: PEChannelOutput = compute_pe_channel(
            ticker=normalized,
            prices=[],
            eps_ttm=None,
            current_price=None,
            cagr=cagr,
        )
        payload = {**asdict(empty), "generated_at": now}
        _pe_cache[normalized] = (now, payload)
        return payload

    result = compute_pe_channel(
        ticker=normalized,
        prices=inputs["prices"],
        eps_ttm=inputs["eps_ttm"],
        current_price=inputs["current_price"],
        cagr=cagr,
    )
    payload = {**asdict(result), "generated_at": now}
    _pe_cache[normalized] = (now, payload)
    return payload
