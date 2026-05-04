from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    ControlResponse,
    PriceAlertRuleCreateRequest,
    PriceAlertRuleUpdateRequest,
    PriceAlertRuleView,
)
from app.services import price_alerts_service

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[PriceAlertRuleView])
async def get_price_alert_rules(
    session: SessionDep,
    symbol: str | None = None,
) -> list[PriceAlertRuleView]:
    try:
        payload = await price_alerts_service.list_rules(session, symbol=symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return [PriceAlertRuleView(**item) for item in payload]


@router.post("", response_model=PriceAlertRuleView)
async def create_price_alert_rule(
    request: PriceAlertRuleCreateRequest,
    session: SessionDep,
) -> PriceAlertRuleView:
    try:
        payload = await price_alerts_service.create_rule(session, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PriceAlertRuleView(**payload)


@router.patch("/{rule_id}", response_model=PriceAlertRuleView)
async def update_price_alert_rule(
    rule_id: int,
    request: PriceAlertRuleUpdateRequest,
    session: SessionDep,
) -> PriceAlertRuleView:
    try:
        payload = await price_alerts_service.update_rule(session, rule_id, request)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "没有找到" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PriceAlertRuleView(**payload)


@router.delete("/{rule_id}", response_model=ControlResponse)
async def delete_price_alert_rule(
    rule_id: int,
    session: SessionDep,
) -> ControlResponse:
    try:
        await price_alerts_service.delete_rule(session, rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return ControlResponse(success=True, message="提醒规则已删除。")
