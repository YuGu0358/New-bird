"""Options-chain analytics endpoints — GEX, walls, max pain, expiry focus.

Distinct from /api/quantlib (which is single-option pricing). Path-prefixed
under /api/options-chain to avoid colliding with the existing quantlib router
or with future broker-side options endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.options_chain import (
    ExpiryFocusResponse,
    FridayScanResponse,
    GexSummaryResponse,
    SqueezeScoreResponse,
)
from app.services import options_chain_service

router = APIRouter(prefix="/api/options-chain", tags=["options-chain"])


@router.get("/{ticker}", response_model=GexSummaryResponse)
async def get_chain_gex(ticker: str, max_expiries: int = 6) -> GexSummaryResponse:
    try:
        payload = await options_chain_service.get_gex_summary(
            ticker, max_expiries=max(1, min(max_expiries, 12))
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return GexSummaryResponse(**payload)


@router.post("/{ticker}/refresh", response_model=GexSummaryResponse)
async def refresh_chain_gex(ticker: str, max_expiries: int = 6) -> GexSummaryResponse:
    try:
        payload = await options_chain_service.get_gex_summary(
            ticker, max_expiries=max(1, min(max_expiries, 12)), force=True
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return GexSummaryResponse(**payload)


@router.get("/{ticker}/friday-scan", response_model=FridayScanResponse)
async def get_friday_scan(
    ticker: str,
    expiry: str | None = None,
    max_expiries: int = 6,
) -> FridayScanResponse:
    """Pinning-probability score for the next Friday (or specified expiry).

    `expiry` is optional — when omitted we pick the next Friday found in the
    chain (or the next available expiry within 7 days).
    """
    try:
        payload = await options_chain_service.get_friday_scan(
            ticker, expiry, max_expiries=max(1, min(max_expiries, 12))
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No chain data available for {ticker.upper()}",
        )
    return FridayScanResponse(**payload)


@router.get("/{ticker}/squeeze", response_model=SqueezeScoreResponse)
async def get_squeeze(ticker: str, max_expiries: int = 6) -> SqueezeScoreResponse:
    """4-factor squeeze score: IV rank + OI concentration + PC ratio + short interest."""
    try:
        payload = await options_chain_service.get_squeeze_score(
            ticker, max_expiries=max(1, min(max_expiries, 12))
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No chain data available for {ticker.upper()}",
        )
    return SqueezeScoreResponse(**payload)


@router.get("/{ticker}/expiry/{expiry}", response_model=ExpiryFocusResponse)
async def get_expiry_focus(
    ticker: str,
    expiry: str,
    max_expiries: int = 6,
    top_n: int = 5,
) -> ExpiryFocusResponse:
    """Drill-in for one expiry: ATM IV, expected move, top OI strikes."""
    try:
        payload = await options_chain_service.get_expiry_focus(
            ticker,
            expiry,
            max_expiries=max(1, min(max_expiries, 12)),
            top_n=max(1, min(top_n, 10)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No contracts found for {ticker.upper()} expiry {expiry}",
        )
    return ExpiryFocusResponse(**payload)
