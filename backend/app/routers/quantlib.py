"""QuantLib endpoints — option pricing, Greeks, bond analytics, VaR."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models import (
    BondAnalyticsRequest,
    BondRiskResponse,
    BondYieldResponse,
    OptionGreeksRequest,
    OptionGreeksResponse,
    OptionPriceRequest,
    OptionPriceResponse,
    VaRRequest,
    VaRResponse,
)
from app.services import quantlib_service
from app.services.quantlib_service import QuantLibInputError

router = APIRouter(prefix="/api/quantlib", tags=["quantlib"])


@router.post("/option/price", response_model=OptionPriceResponse)
async def option_price(request: OptionPriceRequest) -> OptionPriceResponse:
    try:
        return OptionPriceResponse(
            **quantlib_service.option_price(request.model_dump(mode="json"))
        )
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@router.post("/option/greeks", response_model=OptionGreeksResponse)
async def option_greeks(request: OptionGreeksRequest) -> OptionGreeksResponse:
    try:
        return OptionGreeksResponse(
            **quantlib_service.option_greeks(request.model_dump(mode="json"))
        )
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@router.post("/bond/yield", response_model=BondYieldResponse)
async def bond_yield(request: BondAnalyticsRequest) -> BondYieldResponse:
    try:
        return BondYieldResponse(
            **quantlib_service.bond_yield(request.model_dump(mode="json"))
        )
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@router.post("/bond/risk", response_model=BondRiskResponse)
async def bond_risk(request: BondAnalyticsRequest) -> BondRiskResponse:
    try:
        return BondRiskResponse(
            **quantlib_service.bond_risk(request.model_dump(mode="json"))
        )
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@router.post("/var", response_model=VaRResponse)
async def value_at_risk(request: VaRRequest) -> VaRResponse:
    try:
        return VaRResponse(
            **quantlib_service.value_at_risk(request.model_dump(mode="json"))
        )
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
