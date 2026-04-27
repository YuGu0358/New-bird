"""Macro indicator dashboard endpoints.

GET /api/macro              → full dashboard payload
POST /api/macro/refresh     → bypass the in-memory cache and refetch
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.macro import MacroDashboardResponse
from app.services import macro_service
from core.macro import FREDConfigError

router = APIRouter(prefix="/api/macro", tags=["macro"])


@router.get("", response_model=MacroDashboardResponse)
async def get_macro_dashboard() -> MacroDashboardResponse:
    try:
        payload = await macro_service.get_dashboard()
    except FREDConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return MacroDashboardResponse(**payload)


@router.post("/refresh", response_model=MacroDashboardResponse)
async def refresh_macro_dashboard() -> MacroDashboardResponse:
    try:
        payload = await macro_service.get_dashboard(force=True)
    except FREDConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return MacroDashboardResponse(**payload)
