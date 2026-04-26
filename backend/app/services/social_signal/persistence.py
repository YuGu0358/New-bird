"""DB-backed context loaders + execution gating + query-profile builder."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import runtime_settings
from app.database import SocialSignalSnapshot
from app.services import (
    alpaca_service,
    company_profile_service,
    monitoring_service,
    strategy_profiles_service,
)
from app.services.social_providers.x_provider import build_x_query
from app.services.social_signal.classify import _DEFAULT_CONTEXT_TERMS
from app.services.social_signal.local_models import (
    DEFAULT_SOCIAL_LANG,
    DEFAULT_SOCIAL_LOOKBACK_HOURS,
    MAX_SOCIAL_EXECUTIONS_PER_DAY,
    SOCIAL_SIGNAL_COOLDOWN,
    SocialSignalQueryProfile,
)
from app.services.social_signal.normalize import (
    _normalize_keywords,
    _normalize_symbol,
)


async def build_query_profile(
    symbol: str,
    *,
    keywords: Iterable[str] = (),
    hours: int = DEFAULT_SOCIAL_LOOKBACK_HOURS,
    lang: str = DEFAULT_SOCIAL_LANG,
) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_keywords = _normalize_keywords(keywords)

    try:
        profile = await company_profile_service.get_company_profile(normalized_symbol)
        company_name = str(profile.get("company_name") or normalized_symbol).strip()
    except Exception:
        company_name = normalized_symbol

    x_terms = [normalized_symbol]
    if company_name and company_name.upper() != normalized_symbol:
        x_terms.append(f'"{company_name}"')
    for keyword in normalized_keywords[:4]:
        x_terms.append(keyword if " " not in keyword else f'"{keyword}"')

    base_query = " OR ".join(x_terms)
    context_query = " OR ".join(_DEFAULT_CONTEXT_TERMS)
    x_query = build_x_query(
        f"({base_query}) ({context_query})",
        lang=(lang or DEFAULT_SOCIAL_LANG).strip().lower() or DEFAULT_SOCIAL_LANG,
        exclude_reposts=True,
        exclude_replies=True,
    )
    tavily_query = " ".join(
        filter(
            None,
            [
                normalized_symbol,
                company_name if company_name.upper() != normalized_symbol else "",
                " ".join(normalized_keywords),
                "latest market sentiment catalysts",
            ],
        )
    ).strip()

    return SocialSignalQueryProfile(
        symbol=normalized_symbol,
        company_name=company_name or normalized_symbol,
        keywords=normalized_keywords,
        context_terms=list(_DEFAULT_CONTEXT_TERMS),
        x_query=x_query,
        tavily_query=tavily_query or normalized_symbol,
        lang=(lang or DEFAULT_SOCIAL_LANG).strip().lower() or DEFAULT_SOCIAL_LANG,
        hours=max(1, min(int(hours or DEFAULT_SOCIAL_LOOKBACK_HOURS), 72)),
    ).model_dump()


async def _load_positions_map() -> dict[str, dict[str, Any]]:
    try:
        positions = await alpaca_service.list_positions()
    except Exception:
        return {}
    return {
        str(item.get("symbol", "")).upper(): item
        for item in positions
        if str(item.get("symbol", "")).strip()
    }


async def _load_signal_context_symbols(
    session: AsyncSession,
    *,
    include_watchlist: bool,
    include_positions: bool,
    include_candidates: bool,
    force_refresh: bool,
) -> list[str]:
    symbols: list[str] = []
    if include_watchlist:
        await monitoring_service.ensure_default_watchlist(session)
        symbols.extend(await monitoring_service.get_selected_symbols(session))
    if include_candidates:
        candidate_pool = await monitoring_service.build_candidate_pool(session, force_refresh=force_refresh)
        symbols.extend([str(item["symbol"]).upper() for item in candidate_pool])
    if include_positions:
        positions_map = await _load_positions_map()
        symbols.extend(list(positions_map))
    return monitoring_service._normalize_symbols(symbols)  # noqa: SLF001


async def _count_today_executions(session: AsyncSession) -> int:
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(SocialSignalSnapshot)
        .where(SocialSignalSnapshot.executed.is_(True))
        .where(SocialSignalSnapshot.executed_at >= start_of_day)
    )
    return len(result.scalars().all())


async def _latest_executed_snapshot_for_symbol(
    session: AsyncSession,
    symbol: str,
) -> SocialSignalSnapshot | None:
    result = await session.execute(
        select(SocialSignalSnapshot)
        .where(SocialSignalSnapshot.symbol == symbol)
        .where(SocialSignalSnapshot.executed.is_(True))
        .order_by(desc(SocialSignalSnapshot.executed_at), desc(SocialSignalSnapshot.id))
        .limit(1)
    )
    return result.scalars().first()


def _ensure_social_auto_trade_allowed() -> None:
    if not runtime_settings.get_bool_setting("ENABLE_SOCIAL_AUTO_TRADE", default=False):
        raise RuntimeError("当前未开启社媒自动交易。")

    base_url = str(
        runtime_settings.get_setting("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        or "https://paper-api.alpaca.markets"
    ).strip().lower()
    is_paper = "paper-api.alpaca.markets" in base_url
    if is_paper:
        return
    if runtime_settings.get_bool_setting("ALLOW_LIVE_SOCIAL_ORDERS", default=False):
        return
    raise RuntimeError("当前只允许在 Alpaca paper 账户上启用社媒自动交易。")


async def _execute_signal_if_allowed(
    session: AsyncSession,
    *,
    symbol: str,
    action: str,
    confidence: float,
    confidence_label: str,
    has_position: bool,
    final_weight: float,
) -> tuple[bool, str | None, str]:
    if action not in {"buy", "sell", "reduce_or_sell"}:
        return False, None, "当前信号不属于可执行动作。"

    if confidence < 0.7 or confidence_label == "low":
        return False, None, "信号置信度不足，当前不执行自动交易。"

    _ensure_social_auto_trade_allowed()

    previous_execution = await _latest_executed_snapshot_for_symbol(session, symbol)
    if (
        previous_execution is not None
        and previous_execution.executed_at is not None
        and datetime.now(timezone.utc) - previous_execution.executed_at < SOCIAL_SIGNAL_COOLDOWN
    ):
        return False, None, "该股票仍处于社媒自动交易冷却期。"

    today_count = await _count_today_executions(session)
    if today_count >= MAX_SOCIAL_EXECUTIONS_PER_DAY:
        return False, None, "今日社媒自动交易已达到上限。"

    try:
        open_orders = await alpaca_service.list_orders(status="open")
    except Exception:
        open_orders = []

    if any(str(order.get("symbol", "")).upper() == symbol for order in open_orders):
        return False, None, "当前股票已有未完成订单，跳过社媒自动交易。"

    if action == "buy":
        if has_position:
            return False, None, "当前已有持仓，社媒买入信号不重复开仓。"
        _, parameters = await strategy_profiles_service.get_active_strategy_execution_profile()
        order = await alpaca_service.submit_order(
            symbol,
            side="buy",
            notional=float(parameters.initial_buy_notional),
        )
        return True, str(order.get("id") or ""), f"已按社媒信号买入 {parameters.initial_buy_notional:.2f} 美元。"

    if not has_position:
        return False, None, "当前没有持仓，负面信号不会触发做空或卖空。"

    await alpaca_service.close_position(symbol)
    if action == "reduce_or_sell" and final_weight > -50.0:
        return True, None, "已按 reduce_or_sell 信号提交平仓请求（v1 使用全平处理）。"
    return True, None, "已按 sell 信号提交平仓请求。"
