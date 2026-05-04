from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    AssetUniverseItem,
    MonitoringOverview,
    WatchlistUpdateRequest,
)
from app.services import monitoring_service

router = APIRouter(prefix="/api", tags=["monitoring"])


@router.get("/monitoring", response_model=MonitoringOverview)
async def get_monitoring_overview(
    session: SessionDep,
    force_refresh: bool = False,
) -> MonitoringOverview:
    try:
        payload = await monitoring_service.get_monitoring_overview(
            session,
            force_refresh=force_refresh,
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return MonitoringOverview(**payload)


@router.get("/universe", response_model=list[AssetUniverseItem])
async def get_universe(
    query: str = "",
    limit: int = 50,
) -> list[AssetUniverseItem]:
    try:
        payload = await monitoring_service.search_alpaca_universe(query=query, limit=limit)
    except Exception as exc:
        raise service_error(exc) from exc
    return [AssetUniverseItem(**row) for row in payload]


@router.post("/watchlist", response_model=list[str])
async def add_watchlist_symbol(
    request: WatchlistUpdateRequest,
    session: SessionDep,
) -> list[str]:
    try:
        return await monitoring_service.add_watchlist_symbol(session, request.symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@router.delete("/watchlist/{symbol}", response_model=list[str])
async def remove_watchlist_symbol(
    symbol: str,
    session: SessionDep,
) -> list[str]:
    try:
        return await monitoring_service.remove_watchlist_symbol(session, symbol)
    except Exception as exc:
        raise service_error(exc) from exc


@router.post("/monitoring/refresh", response_model=MonitoringOverview)
async def refresh_monitoring(session: SessionDep) -> MonitoringOverview:
    try:
        payload = await monitoring_service.get_monitoring_overview(
            session,
            force_refresh=True,
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return MonitoringOverview(**payload)
