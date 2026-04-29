"""Technical indicator endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.indicators import IndicatorResponse
from app.services import indicators_service

router = APIRouter(prefix="/api/indicators", tags=["indicators"])


@router.get("/{symbol}", response_model=IndicatorResponse)
async def get_indicator(
    symbol: str,
    name: str = "rsi",
    range: str = "3mo",
    period: int | None = None,
    fast: int | None = None,
    slow: int | None = None,
    signal: int | None = None,
    k: float | None = None,
) -> IndicatorResponse:
    """Compute one technical indicator for a symbol's closes.

    Per-indicator params:
    - SMA / EMA / RSI: `period` (default per indicator).
    - MACD: `fast`, `slow`, `signal`.
    - BBANDS: `period`, `k` (stdev multiplier).
    Pass only the params relevant to the chosen indicator; the rest are ignored.
    """
    params: dict[str, int | float] = {}
    if period is not None:
        params["period"] = period
    if fast is not None:
        params["fast"] = fast
    if slow is not None:
        params["slow"] = slow
    if signal is not None:
        params["signal"] = signal
    if k is not None:
        params["k"] = k

    try:
        payload = await indicators_service.compute_for_symbol(
            symbol, name=name, range_name=range, params=params
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return IndicatorResponse(**payload)
