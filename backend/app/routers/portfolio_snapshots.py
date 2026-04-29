"""Read API for /api/portfolio/snapshots."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from app.dependencies import SessionDep, service_error
from app.models.position_snapshots import (
    PositionSnapshotListResponse,
)
from app.services import position_sync_service

router = APIRouter(prefix="/api/portfolio/snapshots", tags=["portfolio"])


@router.get("", response_model=PositionSnapshotListResponse)
async def list_snapshots(
    session: SessionDep,
    broker_account_id: int | None = None,
    symbol: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> PositionSnapshotListResponse:
    """Recent position snapshots, descending by snapshot_at.

    Filter by `broker_account_id`, `symbol`, and/or `since` (UTC ISO).
    `limit` is clamped to [1, 1000].
    """
    try:
        items = await position_sync_service.list_snapshots(
            session,
            broker_account_id=broker_account_id,
            symbol=symbol,
            since=since,
            limit=limit,
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return PositionSnapshotListResponse(items=items)
