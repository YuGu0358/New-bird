"""Async wrapper around core.quantlib.volatility.sabr.

The compute is fast (sub-millisecond per strike); we run it inline
rather than through asyncio.to_thread. The wrapper exists so the router
stays thin and so future enhancements (caching, pre-validation) live
in one place.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.quantlib.volatility import (
    calibrate_sabr,
    sabr_lognormal_vol,
)


async def fit_sabr(
    *,
    forward: float,
    expiry_yrs: float,
    strikes: list[float],
    market_vols: list[float],
    beta: float = 0.5,
) -> dict[str, Any]:
    """Calibrate SABR to a smile and return params + model fit on the input strikes."""
    params, residuals = calibrate_sabr(
        forward,
        expiry_yrs,
        strikes,
        market_vols,
        beta=beta,
    )
    model_vols = [
        sabr_lognormal_vol(
            forward, K, expiry_yrs,
            params.alpha, params.beta, params.rho, params.nu,
        )
        for K in strikes
    ]
    return {
        "forward": forward,
        "expiry_yrs": expiry_yrs,
        "beta": params.beta,
        "alpha": params.alpha,
        "rho": params.rho,
        "nu": params.nu,
        "strikes": list(strikes),
        "market_vols": list(market_vols),
        "model_vols": model_vols,
        "residuals": residuals,
        "generated_at": datetime.now(timezone.utc),
    }
