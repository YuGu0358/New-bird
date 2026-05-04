"""Geopolitical risk events endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.geopolitics import GeopoliticalEventsResponse
from app.services import geopolitics_service

router = APIRouter(prefix="/api/geopolitics", tags=["geopolitics"])


@router.get("/events", response_model=GeopoliticalEventsResponse)
async def get_events(
    region: str | None = None,
    category: str | None = None,
    min_severity: int = 0,
    days_back: int = 365,
    days_ahead: int = 365,
) -> GeopoliticalEventsResponse:
    """Curated geopolitical risk events with severity-ordered ranking."""
    try:
        payload = await geopolitics_service.list_events(
            region=region,
            category=category,
            min_severity=min_severity,
            days_back=days_back,
            days_ahead=days_ahead,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return GeopoliticalEventsResponse(**payload)
