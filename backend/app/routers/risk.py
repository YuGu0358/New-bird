"""Risk policy + audit log endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SessionDep, service_error
from app.models import (
    RiskEventsResponse,
    RiskEventView,
    RiskPolicyConfigUpdateRequest,
    RiskPolicyConfigView,
)
from app.services import risk_service

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/policies", response_model=RiskPolicyConfigView)
async def get_policies(session: SessionDep) -> RiskPolicyConfigView:
    try:
        view = await risk_service.get_config_view(session)
    except Exception as exc:
        raise service_error(exc) from exc
    return RiskPolicyConfigView(**view)


@router.put("/policies", response_model=RiskPolicyConfigView)
async def update_policies(
    request: RiskPolicyConfigUpdateRequest,
    session: SessionDep,
) -> RiskPolicyConfigView:
    try:
        view = await risk_service.update_config(
            session,
            enabled=request.enabled,
            max_position_size_usd=request.max_position_size_usd,
            max_total_exposure_pct=request.max_total_exposure_pct,
            max_open_positions=request.max_open_positions,
            max_daily_loss_usd=request.max_daily_loss_usd,
            blocklist=request.blocklist,
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return RiskPolicyConfigView(**view)


@router.get("/events", response_model=RiskEventsResponse)
async def list_events(session: SessionDep) -> RiskEventsResponse:
    try:
        items = await risk_service.list_recent_events(session)
    except Exception as exc:
        raise service_error(exc) from exc
    return RiskEventsResponse(items=[RiskEventView(**i) for i in items])
