"""Fundamental valuation endpoints — DCF + PE channel."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.valuation import DCFRequest, DCFResponse, PEChannelResponse
from app.services import valuation_service

router = APIRouter(prefix="/api/valuation", tags=["valuation"])


@router.post("/dcf", response_model=DCFResponse)
async def run_dcf(request: DCFRequest) -> DCFResponse:
    try:
        payload = valuation_service.compute_dcf(
            fcfe0=request.fcfe0,
            growth_stage1=request.growth_stage1,
            growth_terminal=request.growth_terminal,
            discount_rate=request.discount_rate,
            years_stage1=request.years_stage1,
            shares_out=request.shares_out,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return DCFResponse(**payload)


@router.get("/pe-channel/{ticker}", response_model=PEChannelResponse)
async def get_pe_channel(ticker: str, lookback_years: int = 10, cagr: float = 0.07) -> PEChannelResponse:
    try:
        payload = await valuation_service.fetch_pe_channel(
            ticker, lookback_years=lookback_years, cagr=cagr
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PEChannelResponse(**payload)
