"""GET /api/signals/{symbol} — surfaces detector output."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path

from app.dependencies import service_error
from app.models import SignalsResponse, SignalView
from app.services import signals_service

router = APIRouter(prefix="/api/signals", tags=["signals"])

# Constrain ticker path-params: 1-16 chars, A-Z 0-9 . - only.
# Prevents path traversal attempts and unbounded strings into yfinance.
_SYMBOL_PATTERN = r"^[A-Za-z0-9.\-]{1,16}$"


@router.get("/{symbol}", response_model=SignalsResponse)
async def get_signals(
    symbol: str = Path(..., pattern=_SYMBOL_PATTERN),
    range: str = "3mo",
) -> SignalsResponse:
    """Run all detectors against the symbol's chart and return the events."""
    try:
        payload = await signals_service.compute_for_symbol(symbol, range_name=range)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return SignalsResponse(
        symbol=payload["symbol"],
        range=payload["range"],
        interval=payload["interval"],
        signals=[SignalView(**s) for s in payload["signals"]],
        generated_at=payload["generated_at"],
    )
