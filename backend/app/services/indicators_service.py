"""Indicator service — pulls bars via chart_service then runs the pure compute.

Reuses chart_service's per-range cache (60s for intraday up to 30 min for
yearly views — see _CHART_RANGE_CONFIG), so a caller asking for both RSI
and MACD on the same range hits yfinance once.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services import chart_service
from core.indicators import INDICATORS, compute_indicator


async def compute_for_symbol(
    symbol: str,
    *,
    name: str,
    range_name: str = "3mo",
    params: dict[str, int | float] | None = None,
) -> dict[str, Any]:
    """Compute `name` indicator on `symbol`'s closes for `range_name`.

    Returns a payload shaped for IndicatorResponse: timestamps + per-series
    values + parameters used. Validates `name` against INDICATORS so the
    error path is HTTP-400 friendly.
    """
    if name not in INDICATORS:
        raise ValueError(
            f"Unknown indicator {name!r}. Supported: {sorted(INDICATORS)}"
        )

    chart = await chart_service.get_symbol_chart(symbol, range_name)
    points = chart.get("points") or []
    timestamps = [p["timestamp"] for p in points]
    closes = [float(p["close"]) for p in points]

    series = compute_indicator(name, closes, params=params)
    effective_params = dict(INDICATORS[name]) | dict(params or {})

    return {
        "symbol": chart["symbol"],
        "range": chart["range"],
        "interval": chart["interval"],
        "indicator": name,
        "params": effective_params,
        "timestamps": timestamps,
        "series": series,
        "generated_at": datetime.now(timezone.utc),
    }
