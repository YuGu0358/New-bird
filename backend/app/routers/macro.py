"""Macro indicator dashboard endpoints.

GET    /api/macro                              full dashboard payload
POST   /api/macro/refresh                      bypass cache and refetch
PUT    /api/macro/indicators/{code}/thresholds save user-customized thresholds
DELETE /api/macro/indicators/{code}/thresholds revert to seed defaults
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models.macro import (
    MacroDashboardResponse,
    MacroThresholdResetResponse,
    MacroThresholdUpdateRequest,
    MacroThresholdUpdateResponse,
)
from app.services import macro_service
from core.macro import FREDConfigError

router = APIRouter(prefix="/api/macro", tags=["macro"])


@router.get("", response_model=MacroDashboardResponse)
async def get_macro_dashboard(session: SessionDep) -> MacroDashboardResponse:
    try:
        payload = await macro_service.get_dashboard(session=session)
    except FREDConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return MacroDashboardResponse(**payload)


@router.post("/refresh", response_model=MacroDashboardResponse)
async def refresh_macro_dashboard(session: SessionDep) -> MacroDashboardResponse:
    try:
        payload = await macro_service.get_dashboard(force=True, session=session)
    except FREDConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return MacroDashboardResponse(**payload)


@router.put("/indicators/{code}/thresholds", response_model=MacroThresholdUpdateResponse)
async def update_indicator_thresholds(
    code: str,
    body: MacroThresholdUpdateRequest,
    session: SessionDep,
) -> MacroThresholdUpdateResponse:
    try:
        payload = await macro_service.upsert_threshold_override(
            session, code=code, thresholds=body.model_dump()
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown indicator: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return MacroThresholdUpdateResponse(**payload)


@router.delete("/indicators/{code}/thresholds", response_model=MacroThresholdResetResponse)
async def reset_indicator_thresholds(
    code: str,
    session: SessionDep,
) -> MacroThresholdResetResponse:
    try:
        removed = await macro_service.delete_threshold_override(session, code=code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown indicator: {exc}") from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return MacroThresholdResetResponse(code=code, removed=removed)
