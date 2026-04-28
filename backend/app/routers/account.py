from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import desc, select

from app.database import Trade
from app.dependencies import BrokerDep, SessionDep, service_error
from app.models import (
    Account,
    ControlResponse,
    OrderRecord,
    Position,
    TradeRecord,
)
from app.services import alpaca_service

router = APIRouter(prefix="/api", tags=["account"])


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.get("/account", response_model=Account)
async def get_account(broker: BrokerDep) -> Account:
    try:
        payload = await broker.get_account()
    except Exception as exc:
        raise service_error(exc) from exc
    return Account(**payload)


@router.get("/positions", response_model=list[Position])
async def get_positions(broker: BrokerDep) -> list[Position]:
    try:
        payload = await broker.list_positions()
    except Exception as exc:
        raise service_error(exc) from exc
    return [Position(**row) for row in payload]


@router.get("/trades", response_model=list[TradeRecord])
async def get_trades(session: SessionDep) -> list[TradeRecord]:
    result = await session.execute(
        select(Trade).order_by(desc(Trade.exit_date), desc(Trade.id))
    )
    trades = result.scalars().all()
    return [TradeRecord.model_validate(item) for item in trades]


@router.get("/orders", response_model=list[OrderRecord])
async def get_orders(broker: BrokerDep, status: str = "all") -> list[OrderRecord]:
    try:
        payload = await broker.list_orders(status=status)
    except Exception as exc:
        raise service_error(exc) from exc
    return [OrderRecord(**row) for row in payload]


@router.post("/orders/cancel", response_model=ControlResponse)
async def cancel_orders() -> ControlResponse:
    try:
        cancelled_count = await alpaca_service.cancel_all_orders()
    except Exception as exc:
        raise service_error(exc) from exc

    return ControlResponse(
        success=True,
        message=f"已提交撤销挂单请求，共处理 {cancelled_count} 笔订单。",
    )


@router.post("/positions/close", response_model=ControlResponse)
async def close_positions() -> ControlResponse:
    try:
        submitted_count = await alpaca_service.close_all_positions()
    except Exception as exc:
        raise service_error(exc) from exc

    return ControlResponse(
        success=True,
        message=f"已提交全部平仓请求，共处理 {submitted_count} 个持仓。",
    )
