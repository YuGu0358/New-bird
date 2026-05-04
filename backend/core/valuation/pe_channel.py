"""PE-channel valuation — historical PE percentile bands.

Inputs:
    - prices: list of historical close prices (most recent last)
    - eps_ttm: current trailing-twelve-month EPS
    - cagr: assumed historical EPS growth rate (default 7%) used to back-project
            historical EPS — yfinance doesn't give us a clean per-day EPS series.

Outputs: percentile bands (5/25/50/75/95) of historical PE × current EPS →
fair-price bands.

This is intentionally lightweight; richer fundamentals (FMP forward EPS, etc.)
would replace the back-projection step. Until then it's still a useful sanity
check ("am I paying p95 or p25 of the historical multiple?").
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PEChannelOutput:
    ticker: str
    current_price: float | None
    ttm_eps: float | None
    current_pe: float | None
    pe_p5: float | None
    pe_p25: float | None
    pe_p50: float | None
    pe_p75: float | None
    pe_p95: float | None
    fair_p5: float | None
    fair_p25: float | None
    fair_p50: float | None
    fair_p75: float | None
    fair_p95: float | None
    sample_size: int


def compute_pe_channel(
    *,
    ticker: str,
    prices: list[float],
    eps_ttm: float | None,
    current_price: float | None = None,
    cagr: float = 0.07,
) -> PEChannelOutput:
    """Compute PE-channel from a price series and a single current TTM EPS.

    The historical PE series is approximated as::

        PE(t) = price(t) / eps(t)
        eps(t) = eps_ttm / (1 + cagr) ** (years_back(t))

    So a stock that grew EPS at exactly `cagr` collapses to a flat PE — the
    fluctuations come from the multiple expansion/compression around that.
    """
    n = len(prices)
    if not current_price:
        current_price = prices[-1] if prices else None

    if n == 0 or eps_ttm in (None, 0):
        return PEChannelOutput(
            ticker=ticker.upper(),
            current_price=current_price,
            ttm_eps=eps_ttm,
            current_pe=(current_price / eps_ttm) if (current_price and eps_ttm) else None,
            pe_p5=None,
            pe_p25=None,
            pe_p50=None,
            pe_p75=None,
            pe_p95=None,
            fair_p5=None,
            fair_p25=None,
            fair_p50=None,
            fair_p75=None,
            fair_p95=None,
            sample_size=n,
        )

    arr = np.asarray(prices, dtype=float)
    days_back = np.arange(n)[::-1]  # 0 = today, n-1 = oldest
    historical_eps = float(eps_ttm) / (1 + cagr) ** (days_back / 252.0)
    historical_pe = arr / historical_eps

    p5 = float(np.quantile(historical_pe, 0.05))
    p25 = float(np.quantile(historical_pe, 0.25))
    p50 = float(np.quantile(historical_pe, 0.50))
    p75 = float(np.quantile(historical_pe, 0.75))
    p95 = float(np.quantile(historical_pe, 0.95))

    current_pe = (current_price / eps_ttm) if (current_price and eps_ttm) else None

    return PEChannelOutput(
        ticker=ticker.upper(),
        current_price=current_price,
        ttm_eps=float(eps_ttm),
        current_pe=current_pe,
        pe_p5=p5,
        pe_p25=p25,
        pe_p50=p50,
        pe_p75=p75,
        pe_p95=p95,
        fair_p5=eps_ttm * p5,
        fair_p25=eps_ttm * p25,
        fair_p50=eps_ttm * p50,
        fair_p75=eps_ttm * p75,
        fair_p95=eps_ttm * p95,
        sample_size=n,
    )
