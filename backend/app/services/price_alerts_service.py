from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import runtime_settings
from app.database import AsyncSessionLocal, PriceAlertRule
from app.models import PriceAlertRuleCreateRequest, PriceAlertRuleUpdateRequest
from app.services import alpaca_service, email_service

logger = logging.getLogger(__name__)

ALERT_POLL_INTERVAL_SECONDS = 20

_CONDITION_TYPES = {
    "price_above",
    "price_below",
    "day_change_up",
    "day_change_down",
}
_ACTION_TYPES = {
    "email",
    "buy_notional",
    "close_position",
}


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        raise ValueError("股票代码不能为空。")
    return normalized


def _normalize_condition_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _CONDITION_TYPES:
        raise ValueError("不支持的触发条件。")
    return normalized


def _normalize_action_type(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _ACTION_TYPES:
        raise ValueError("不支持的触发动作。")
    return normalized


def _format_usd(value: float | None) -> str:
    if value is None:
        return "暂无"
    return f"{float(value):.2f} 美元"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "暂无"
    return f"{value:+.2f}%"


def _condition_summary(condition_type: str, target_value: float) -> str:
    if condition_type == "price_above":
        return f"价格涨到 {_format_usd(target_value)} 以上"
    if condition_type == "price_below":
        return f"价格跌到 {_format_usd(target_value)} 以下"
    if condition_type == "day_change_up":
        return f"相对昨收涨幅达到 +{float(target_value):.2f}%"
    return f"相对昨收跌幅达到 -{float(target_value):.2f}%"


def _action_summary(action_type: str, order_notional_usd: float | None) -> str:
    if action_type == "email":
        return "触发后发送邮件提醒"
    if action_type == "buy_notional":
        return f"触发后自动买入 {_format_usd(order_notional_usd)}"
    return "触发后自动平掉当前持仓"


def _serialize_rule(rule: PriceAlertRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "symbol": rule.symbol,
        "condition_type": rule.condition_type,
        "condition_summary": _condition_summary(rule.condition_type, rule.target_value),
        "target_value": rule.target_value,
        "action_type": rule.action_type,
        "action_summary": _action_summary(rule.action_type, rule.order_notional_usd),
        "order_notional_usd": rule.order_notional_usd,
        "note": rule.note,
        "enabled": rule.enabled,
        "triggered_at": rule.triggered_at,
        "trigger_price": rule.trigger_price,
        "trigger_change_percent": rule.trigger_change_percent,
        "action_result": rule.action_result,
        "last_error": rule.last_error,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def _compute_day_change_percent(current_price: float, previous_close: float | None) -> float | None:
    if previous_close is None or previous_close <= 0:
        return None
    return round(((current_price - previous_close) / previous_close) * 100, 2)


def _is_rule_triggered(
    *,
    condition_type: str,
    target_value: float,
    current_price: float,
    day_change_percent: float | None,
) -> bool:
    if condition_type == "price_above":
        return current_price >= target_value
    if condition_type == "price_below":
        return current_price <= target_value
    if day_change_percent is None:
        return False
    if condition_type == "day_change_up":
        return day_change_percent >= target_value
    return day_change_percent <= -abs(target_value)


def _ensure_auto_trade_allowed() -> None:
    base_url = str(
        runtime_settings.get_setting("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        or "https://paper-api.alpaca.markets"
    ).strip().lower()
    is_paper = "paper-api.alpaca.markets" in base_url
    if is_paper:
        return
    if runtime_settings.get_bool_setting("ALLOW_LIVE_ALERT_ORDERS", default=False):
        return
    raise RuntimeError("当前只允许在 Alpaca paper 账户上启用自动交易提醒。")


async def list_rules(session: AsyncSession, symbol: str | None = None) -> list[dict[str, Any]]:
    statement = select(PriceAlertRule)
    if symbol:
        statement = statement.where(PriceAlertRule.symbol == _normalize_symbol(symbol))
    statement = statement.order_by(
        desc(PriceAlertRule.enabled),
        desc(PriceAlertRule.updated_at),
        desc(PriceAlertRule.id),
    )
    result = await session.execute(statement)
    return [_serialize_rule(item) for item in result.scalars().all()]


async def create_rule(
    session: AsyncSession,
    request: PriceAlertRuleCreateRequest,
) -> dict[str, Any]:
    symbol = _normalize_symbol(request.symbol)
    condition_type = _normalize_condition_type(request.condition_type)
    action_type = _normalize_action_type(request.action_type)
    target_value = float(request.target_value or 0)
    if target_value <= 0:
        raise ValueError("触发价格或涨跌幅必须大于 0。")

    order_notional_usd = None
    if action_type == "buy_notional":
        order_notional_usd = float(request.order_notional_usd or 0)
        if order_notional_usd <= 0:
            raise ValueError("自动买入规则需要填写有效的美元金额。")

    now = datetime.now(timezone.utc)
    rule = PriceAlertRule(
        symbol=symbol,
        condition_type=condition_type,
        target_value=target_value,
        action_type=action_type,
        order_notional_usd=order_notional_usd,
        note=str(request.note or "").strip(),
        enabled=True,
        triggered_at=None,
        trigger_price=None,
        trigger_change_percent=None,
        action_result="",
        last_error="",
        created_at=now,
        updated_at=now,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return _serialize_rule(rule)


async def update_rule(
    session: AsyncSession,
    rule_id: int,
    request: PriceAlertRuleUpdateRequest,
) -> dict[str, Any]:
    result = await session.execute(select(PriceAlertRule).where(PriceAlertRule.id == rule_id))
    rule = result.scalars().first()
    if rule is None:
        raise ValueError("没有找到对应的提醒规则。")

    rule.enabled = bool(request.enabled)
    rule.updated_at = datetime.now(timezone.utc)
    if rule.enabled:
        rule.triggered_at = None
        rule.trigger_price = None
        rule.trigger_change_percent = None
        rule.action_result = ""
        rule.last_error = ""

    await session.commit()
    await session.refresh(rule)
    return _serialize_rule(rule)


async def delete_rule(session: AsyncSession, rule_id: int) -> None:
    result = await session.execute(select(PriceAlertRule).where(PriceAlertRule.id == rule_id))
    rule = result.scalars().first()
    if rule is None:
        raise ValueError("没有找到对应的提醒规则。")
    await session.delete(rule)
    await session.commit()


async def _execute_rule_action(
    rule: PriceAlertRule,
    *,
    current_price: float,
    day_change_percent: float | None,
) -> str:
    if rule.action_type == "email":
        subject = f"[Newbird] {rule.symbol} 已触发提醒"
        body = "\n".join(
            [
                f"股票：{rule.symbol}",
                f"条件：{_condition_summary(rule.condition_type, rule.target_value)}",
                f"当前价格：{_format_usd(current_price)}",
                f"相对昨收：{_format_percent(day_change_percent)}",
                f"动作：{_action_summary(rule.action_type, rule.order_notional_usd)}",
                f"备注：{rule.note or '无'}",
            ]
        )
        await email_service.send_price_alert_email(subject, body)
        return "已发送邮件提醒。"

    _ensure_auto_trade_allowed()

    if rule.action_type == "buy_notional":
        await alpaca_service.submit_order(
            rule.symbol,
            side="buy",
            notional=float(rule.order_notional_usd or 0),
        )
        return f"已自动买入 {_format_usd(rule.order_notional_usd)}。"

    await alpaca_service.close_position(rule.symbol)
    return "已提交自动平仓请求。"


async def evaluate_rules_once(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    session_factory = session_factory or AsyncSessionLocal

    async with session_factory() as session:
        result = await session.execute(
            select(PriceAlertRule)
            .where(PriceAlertRule.enabled.is_(True))
            .order_by(PriceAlertRule.created_at, PriceAlertRule.id)
        )
        rules = result.scalars().all()
        if not rules:
            return 0

        symbols = sorted({rule.symbol for rule in rules})
        snapshots = await alpaca_service.get_market_snapshots(symbols)
        if not snapshots:
            return 0

        now = datetime.now(timezone.utc)
        triggered_count = 0

        for rule in rules:
            snapshot = snapshots.get(rule.symbol)
            if snapshot is None:
                continue

            current_price = float(snapshot.get("price", 0) or 0)
            previous_close = snapshot.get("previous_close")
            if current_price <= 0:
                continue

            day_change_percent = _compute_day_change_percent(
                current_price,
                float(previous_close) if previous_close is not None else None,
            )
            if not _is_rule_triggered(
                condition_type=rule.condition_type,
                target_value=rule.target_value,
                current_price=current_price,
                day_change_percent=day_change_percent,
            ):
                continue

            triggered_count += 1
            rule.enabled = False
            rule.triggered_at = now
            rule.trigger_price = current_price
            rule.trigger_change_percent = day_change_percent
            rule.updated_at = now

            try:
                rule.action_result = await _execute_rule_action(
                    rule,
                    current_price=current_price,
                    day_change_percent=day_change_percent,
                )
                rule.last_error = ""
            except Exception as exc:
                rule.action_result = "触发后执行失败。"
                rule.last_error = str(exc)
                logger.exception("Price alert action failed for %s", rule.symbol)

            try:
                from app.services import notifications_service

                await notifications_service.dispatch_price_alert(
                    symbol=rule.symbol,
                    condition=_condition_summary(rule.condition_type, rule.target_value),
                    target_value=float(rule.target_value)
                    if rule.target_value is not None
                    else None,
                    current_price=current_price,
                    day_change_percent=day_change_percent,
                    note=rule.note or None,
                )
            except Exception:
                # Notifications must never block the monitor.
                logger.exception("Price alert notification failed for %s", rule.symbol)

        await session.commit()
        return triggered_count
