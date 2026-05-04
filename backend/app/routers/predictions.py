"""Prediction-market endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.predictions import PredictionMarketsResponse
from app.services import polymarket_service

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("/markets", response_model=PredictionMarketsResponse)
async def get_markets(
    limit: int = 25,
    sort_by: str = "volume_usd",
    descending: bool = True,
) -> PredictionMarketsResponse:
    """Polymarket top-N active markets — opt-in via POLYMARKET_ENABLED."""
    try:
        payload = await polymarket_service.get_markets(
            limit=limit, sort_by=sort_by, descending=descending
        )
    except RuntimeError as exc:
        if "disabled" in str(exc).lower():
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise service_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PredictionMarketsResponse(**payload)
