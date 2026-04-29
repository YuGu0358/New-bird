"""Kraken public-data endpoints (read-only, opt-in)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.kraken import KrakenTickerResponse, KrakenTradesResponse
from app.services import kraken_service

router = APIRouter(prefix="/api/kraken", tags=["kraken"])


@router.get("/ticker/{pair}", response_model=KrakenTickerResponse)
async def get_ticker(pair: str) -> KrakenTickerResponse:
    """Kraken Ticker for a single pair (e.g. `XBTUSD`).

    Read-only, opt-in via KRAKEN_ENABLED. Surfaces 503 when disabled or
    when Kraken returns an error envelope.
    """
    try:
        payload = await kraken_service.get_ticker(pair)
    except RuntimeError as exc:
        if "disabled" in str(exc).lower():
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise service_error(exc) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return KrakenTickerResponse(**payload)


@router.get("/trades/{pair}", response_model=KrakenTradesResponse)
async def get_recent_trades(pair: str) -> KrakenTradesResponse:
    """Recent Kraken trade prints for a pair."""
    try:
        payload = await kraken_service.get_recent_trades(pair)
    except RuntimeError as exc:
        if "disabled" in str(exc).lower():
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise service_error(exc) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return KrakenTradesResponse(**payload)
