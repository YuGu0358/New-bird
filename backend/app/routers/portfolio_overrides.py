"""Per-position override CRUD."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models.position_overrides import (
    PositionOverrideListResponse,
    PositionOverrideUpsertRequest,
    PositionOverrideView,
)
from app.services import position_overrides_service

router = APIRouter(prefix="/api/portfolio/overrides", tags=["portfolio"])


@router.get("", response_model=PositionOverrideListResponse)
async def list_overrides(
    session: SessionDep,
    broker_account_id: int | None = None,
    ticker: str | None = None,
) -> PositionOverrideListResponse:
    items = await position_overrides_service.list_overrides(
        session,
        broker_account_id=broker_account_id,
        ticker=ticker,
    )
    return PositionOverrideListResponse(items=items)


@router.get(
    "/{broker_account_id}/{ticker}",
    response_model=PositionOverrideView,
)
async def get_override(
    broker_account_id: int,
    ticker: str,
    session: SessionDep,
) -> PositionOverrideView:
    payload = await position_overrides_service.get_override(
        session, broker_account_id, ticker
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Override not found")
    return PositionOverrideView(**payload)


@router.put("", response_model=PositionOverrideView)
async def upsert_override(
    request: PositionOverrideUpsertRequest,
    session: SessionDep,
) -> PositionOverrideView:
    """Upsert: creates if missing, replaces fields if present.

    Pass null for stop_price / take_profit_price / notes / tier_override
    to clear them on update. Omitted fields default to null on create.
    Pydantic does NOT distinguish absent vs explicit-null, so for partial
    updates use the GET-modify-PUT pattern from the client.
    """
    try:
        payload = await position_overrides_service.set_override(
            session,
            broker_account_id=request.broker_account_id,
            ticker=request.ticker,
            stop_price=request.stop_price,
            take_profit_price=request.take_profit_price,
            notes=request.notes,
            tier_override=request.tier_override,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PositionOverrideView(**payload)


@router.delete(
    "/{broker_account_id}/{ticker}",
    status_code=204,
)
async def delete_override(
    broker_account_id: int,
    ticker: str,
    session: SessionDep,
) -> None:
    deleted = await position_overrides_service.delete_override(
        session, broker_account_id, ticker
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Override not found")
    return None
