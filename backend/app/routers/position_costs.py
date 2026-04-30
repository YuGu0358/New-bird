"""REST surface for position_costs."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import AdminTokenDep, SessionDep, service_error
from app.models import (
    PositionCostBuyRequest,
    PositionCostListResponse,
    PositionCostUpsertRequest,
    PositionCostView,
)
from app.services import position_costs_service

router = APIRouter(prefix="/api/position-costs", tags=["position-costs"])


@router.get("", response_model=PositionCostListResponse)
async def list_costs(broker_account_id: int, session: SessionDep) -> PositionCostListResponse:
    try:
        items = await position_costs_service.list_for_account(
            session, broker_account_id=broker_account_id
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return PositionCostListResponse(items=[PositionCostView(**i) for i in items])


@router.get("/{broker_account_id}/{ticker}", response_model=PositionCostView)
async def get_cost(broker_account_id: int, ticker: str, session: SessionDep) -> PositionCostView:
    try:
        view = await position_costs_service.get_one(
            session, broker_account_id=broker_account_id, ticker=ticker
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if view is None:
        raise HTTPException(status_code=404, detail="Position cost not found")
    return PositionCostView(**view)


@router.put("", response_model=PositionCostView, dependencies=[AdminTokenDep])
async def upsert_cost(request: PositionCostUpsertRequest, session: SessionDep) -> PositionCostView:
    try:
        view = await position_costs_service.upsert(
            session,
            broker_account_id=request.broker_account_id,
            ticker=request.ticker,
            avg_cost_basis=request.avg_cost_basis,
            total_shares=request.total_shares,
            custom_stop_loss=request.custom_stop_loss,
            custom_take_profit=request.custom_take_profit,
            notes=request.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PositionCostView(**view)


@router.post("/buy", response_model=PositionCostView, dependencies=[AdminTokenDep])
async def record_buy(request: PositionCostBuyRequest, session: SessionDep) -> PositionCostView:
    try:
        view = await position_costs_service.record_buy(
            session,
            broker_account_id=request.broker_account_id,
            ticker=request.ticker,
            fill_price=request.fill_price,
            fill_qty=request.fill_qty,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PositionCostView(**view)


@router.delete("/{broker_account_id}/{ticker}", status_code=204, dependencies=[AdminTokenDep])
async def delete_cost(broker_account_id: int, ticker: str, session: SessionDep) -> None:
    try:
        deleted = await position_costs_service.delete(
            session, broker_account_id=broker_account_id, ticker=ticker
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Position cost not found")
    return None
