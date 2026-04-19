from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import runtime_settings
from app.database import SocialSignalSnapshot
from app.services import (
    alpaca_service,
    company_profile_service,
    monitoring_service,
    openai_service,
    social_intelligence_service,
    strategy_profiles_service,
    tavily_service,
)
from app.services.social_providers.x_provider import build_x_query

logger = logging.getLogger(__name__)

DEFAULT_SOCIAL_LOOKBACK_HOURS = 6
DEFAULT_SOCIAL_POST_LIMIT = 30
DEFAULT_SOCIAL_LANG = "en"
DEFAULT_SOCIAL_POLL_INTERVAL_MINUTES = 15
SOCIAL_SIGNAL_COOLDOWN = timedelta(minutes=60)
MAX_SOCIAL_EXECUTIONS_PER_DAY = 3
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16

_GENERIC_COMPANY_TOKENS = {
    "inc",
    "corp",
    "corporation",
    "company",
    "co",
    "ltd",
    "limited",
    "group",
    "holdings",
    "technologies",
    "technology",
    "plc",
    "the",
}
_POSITIVE_TERMS = {
    "beat",
    "beats",
    "bullish",
    "upgrade",
    "upgraded",
    "strong",
    "outperform",
    "buy",
    "buying",
    "accumulate",
    "undervalued",
    "momentum",
    "growth",
    "record",
    "surge",
    "rally",
    "raised guidance",
    "guidance raise",
    "guidance raised",
    "demand strong",
    "profit growth",
    "margin expansion",
}
_NEGATIVE_TERMS = {
    "miss",
    "missed",
    "bearish",
    "downgrade",
    "downgraded",
    "weak",
    "sell",
    "selling",
    "overvalued",
    "cut guidance",
    "guidance cut",
    "decline",
    "drop",
    "lawsuit",
    "probe",
    "fraud",
    "delay",
    "short",
    "margin pressure",
    "warning",
    "risk-off",
}
_UNCERTAIN_TERMS = {
    "rumor",
    "maybe",
    "might",
    "unclear",
    "unconfirmed",
    "speculation",
    "speculative",
}
_DEFAULT_CONTEXT_TERMS = (
    "earnings",
    "guidance",
    "demand",
    "revenue",
    "upgrade",
    "downgrade",
    "product",
    "regulation",
)


class SocialSignalQueryProfile(BaseModel):
    symbol: str
    company_name: str
    keywords: list[str]
    context_terms: list[str]
    x_query: str
    tavily_query: str
    lang: str = DEFAULT_SOCIAL_LANG
    hours: int = DEFAULT_SOCIAL_LOOKBACK_HOURS


class SocialTextClassification(BaseModel):
    label: Literal["bullish", "bearish", "neutral", "irrelevant"]
    confidence: float
    rationale: str = ""
    mention_entity: bool = True


class _OpenAIClassificationResponse(BaseModel):
    label: Literal["bullish", "bearish", "neutral", "irrelevant"]
    confidence: float
    rationale: str
    mention_entity: bool


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        raise ValueError("股票代码不能为空。")
    return normalized


def _normalize_keywords(keywords: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for value in keywords:
        text = str(value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    normalized = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _format_source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("title", "")).strip(),
        "url": str(item.get("url", "")).strip(),
        "content": str(item.get("content", "")).strip(),
        "source": item.get("source"),
        "domain": item.get("domain"),
        "published_date": item.get("published_date"),
        "score": float(item.get("score", 0.0) or 0.0),
    }


def _source_failure_reason(source_name: str, exc: BaseException) -> str:
    message = str(exc).strip()
    lowered = message.lower()
    if "missing" in lowered or "api key" in lowered or "token" in lowered or "缺少" in lowered:
        return f"{source_name} 数据源未配置或认证失败，已按空样本降级处理。"
    if "rate" in lowered or "limit" in lowered or "429" in lowered or "限流" in lowered:
        return f"{source_name} 数据源触发限流，已按空样本降级处理。"
    if "timeout" in lowered or "timed out" in lowered or "超时" in lowered:
        return f"{source_name} 数据源请求超时，已按空样本降级处理。"
    return f"{source_name} 数据源暂时不可用，已按空样本降级处理。"


def _build_company_aliases(symbol: str, company_name: str) -> list[str]:
    aliases = [symbol.upper()]
    normalized_company_name = str(company_name or "").strip()
    if normalized_company_name and normalized_company_name.upper() != symbol.upper():
        aliases.append(normalized_company_name)

    for token in re.split(r"[^A-Za-z0-9]+", normalized_company_name.lower()):
        if len(token) < 3 or token in _GENERIC_COMPANY_TOKENS:
            continue
        aliases.append(token)

    unique_aliases: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        normalized = alias.strip()
        if not normalized:
            continue
        cache_key = normalized.lower()
        if cache_key in seen:
            continue
        seen.add(cache_key)
        unique_aliases.append(normalized)
    return unique_aliases


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


def _count_phrase_hits(text: str, terms: set[str]) -> int:
    total = 0
    lowered = text.lower()
    for term in terms:
        if term in lowered:
            total += lowered.count(term)
    return total


def _local_classify_text(
    text: str,
    *,
    symbol: str,
    aliases: list[str],
) -> SocialTextClassification:
    normalized_text = " ".join(str(text or "").split())
    lowered = normalized_text.lower()
    mention_entity = symbol.lower() in lowered or any(alias.lower() in lowered for alias in aliases)
    if not mention_entity:
        return SocialTextClassification(
            label="irrelevant",
            confidence=0.32,
            rationale="文本没有明确提到目标股票或公司实体。",
            mention_entity=False,
        )

    positive_hits = _count_phrase_hits(lowered, _POSITIVE_TERMS)
    negative_hits = _count_phrase_hits(lowered, _NEGATIVE_TERMS)
    uncertain_hits = _count_phrase_hits(lowered, _UNCERTAIN_TERMS)
    total_hits = positive_hits + negative_hits

    if total_hits == 0:
        confidence = 0.58 - min(uncertain_hits * 0.05, 0.12)
        return SocialTextClassification(
            label="neutral",
            confidence=_clip(confidence, 0.35, 0.62),
            rationale="文本提到了目标股票，但缺少明显的多空倾向。",
            mention_entity=True,
        )

    score = positive_hits - negative_hits
    if score == 0:
        confidence = 0.6 - min(uncertain_hits * 0.05, 0.15)
        return SocialTextClassification(
            label="neutral",
            confidence=_clip(confidence, 0.35, 0.7),
            rationale="文本同时包含正负信号，多空倾向不明显。",
            mention_entity=True,
        )

    label: Literal["bullish", "bearish", "neutral", "irrelevant"] = "bullish" if score > 0 else "bearish"
    confidence = 0.55 + min(total_hits, 4) * 0.07 + min(abs(score), 3) * 0.05
    confidence -= min(uncertain_hits * 0.05, 0.15)
    confidence = _clip(confidence, 0.35, 0.92)
    rationale = "本地词典分类命中偏多信号。" if label == "bullish" else "本地词典分类命中偏空信号。"
    return SocialTextClassification(
        label=label,
        confidence=confidence,
        rationale=rationale,
        mention_entity=True,
    )


def _openai_classify_text_sync(
    text: str,
    *,
    symbol: str,
    company_name: str,
) -> SocialTextClassification:
    client = openai_service.create_client()
    model_name = (
        runtime_settings.get_setting("OPENAI_SOCIAL_MODEL", "gpt-4o-2024-08-06")
        or "gpt-4o-2024-08-06"
    )
    response = client.responses.parse(
        model=model_name,
        instructions=(
            "你是股票社媒分类器。"
            "只判断文本相对目标股票的多空倾向，不给出交易建议。"
            "标签必须是 bullish、bearish、neutral、irrelevant 之一。"
        ),
        input=[
            {
                "role": "user",
                "content": (
                    f"目标股票：{symbol}\n"
                    f"公司名称：{company_name}\n"
                    f"文本：{text}\n\n"
                    "请判断这段文本是否真的在讨论该股票，如果是，再判断倾向。"
                ),
            }
        ],
        text_format=_OpenAIClassificationResponse,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI social classifier returned no structured payload.")
    return SocialTextClassification(
        label=parsed.label,
        confidence=_clip(float(parsed.confidence), 0.0, 1.0),
        rationale=parsed.rationale.strip(),
        mention_entity=bool(parsed.mention_entity),
    )


async def _classify_text(
    text: str,
    *,
    symbol: str,
    company_name: str,
    aliases: list[str],
) -> SocialTextClassification:
    local_result = _local_classify_text(text, symbol=symbol, aliases=aliases)
    if (
        local_result.confidence >= 0.65
        and local_result.mention_entity
        and local_result.label != "irrelevant"
    ):
        return local_result

    if not openai_service.is_configured():
        return local_result

    try:
        remote_result = await asyncio.to_thread(
            _openai_classify_text_sync,
            text,
            symbol=symbol,
            company_name=company_name,
        )
        if remote_result.confidence >= local_result.confidence:
            return remote_result
    except Exception:
        logger.exception("OpenAI social fallback classification failed for %s", symbol)

    return local_result


def _engagement_weight(metrics: dict[str, Any]) -> float:
    likes = int(metrics.get("like_count", 0) or 0)
    reposts = int(metrics.get("repost_count", 0) or 0)
    replies = int(metrics.get("reply_count", 0) or 0)
    quotes = int(metrics.get("quote_count", 0) or 0)
    engagement = likes + (2 * reposts) + (1.2 * replies) + (1.5 * quotes)
    return min(math.log1p(max(engagement, 0)) / 5.0, 1.5)


def _author_weight(author: dict[str, Any]) -> float:
    followers = int(author.get("followers_count", 0) or 0)
    verified_bonus = 0.15 if author.get("verified") else 0.0
    return min(math.log10(followers + 10) / 2.0, 1.5) + verified_bonus


def _recency_weight(created_at: datetime, now: datetime) -> float:
    age_hours = max((now - created_at).total_seconds() / 3600.0, 0.0)
    return math.exp(-(age_hours / 12.0))


def _sentiment_sign(label: str) -> int:
    if label == "bullish":
        return 1
    if label == "bearish":
        return -1
    return 0


def _classify_confidence_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def _compute_market_score(trend: dict[str, Any]) -> float:
    day = float(trend.get("day_change_percent") or 0.0)
    week = float(trend.get("week_change_percent") or 0.0)
    month = float(trend.get("month_change_percent") or 0.0)
    day_p = _clip(day, -10.0, 10.0)
    week_p = _clip(week, -20.0, 20.0)
    month_p = _clip(month, -40.0, 40.0)
    score = 100.0 * ((0.25 * day_p / 10.0) + (0.35 * week_p / 20.0) + (0.40 * month_p / 40.0))
    return round(_clip(score, -100.0, 100.0), 4)


def _map_action(final_weight: float, *, has_position: bool) -> str:
    if final_weight >= 35.0:
        return "buy"
    if final_weight >= 15.0:
        return "bullish_watch"
    if has_position and final_weight <= -50.0:
        return "sell"
    if has_position and final_weight <= -25.0:
        return "reduce_or_sell"
    if not has_position and final_weight <= -15.0:
        return "avoid"
    return "hold"


def _downgrade_action(action: str) -> str:
    if action == "buy":
        return "bullish_watch"
    if action in {"sell", "reduce_or_sell", "avoid"}:
        return "hold"
    return action


def _serialize_snapshot(snapshot: SocialSignalSnapshot) -> dict[str, Any]:
    return {
        "symbol": snapshot.symbol,
        "generated_at": snapshot.snapshot_at,
        "query_profile": json.loads(snapshot.query_profile_json),
        "social_score": snapshot.social_score,
        "market_score": snapshot.market_score,
        "final_weight": snapshot.final_weight,
        "action": snapshot.action,
        "confidence": snapshot.confidence,
        "confidence_label": snapshot.confidence_label,
        "reasons": json.loads(snapshot.reasons_json),
        "top_posts": json.loads(snapshot.top_posts_json),
        "top_sources": json.loads(snapshot.top_sources_json),
        "executed": snapshot.executed,
        "executed_order_id": snapshot.executed_order_id,
        "execution_message": snapshot.execution_message,
    }


def is_market_session_open(now: datetime | None = None) -> bool:
    current_time = now or datetime.now(timezone.utc)
    eastern_now = current_time.astimezone(ZoneInfo("America/New_York"))
    if eastern_now.weekday() >= 5:
        return False
    open_time = eastern_now.replace(
        hour=MARKET_OPEN_HOUR,
        minute=MARKET_OPEN_MINUTE,
        second=0,
        microsecond=0,
    )
    close_time = eastern_now.replace(
        hour=MARKET_CLOSE_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    return open_time <= eastern_now <= close_time


async def _classify_posts(
    posts: list[dict[str, Any]],
    *,
    symbol: str,
    company_name: str,
    aliases: list[str],
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    classified: list[dict[str, Any]] = []
    for post in posts:
        classification = await _classify_text(
            post.get("text", ""),
            symbol=symbol,
            company_name=company_name,
            aliases=aliases,
        )
        created_at = _parse_timestamp(post.get("created_at"))
        metrics = post.get("metrics", {}) or {}
        weight = (
            _recency_weight(created_at, now)
            * _engagement_weight(metrics)
            * _author_weight(post.get("author", {}) or {})
            * classification.confidence
        )
        enriched = dict(post)
        enriched["classification"] = classification.model_dump()
        enriched["weight"] = round(weight, 6)
        classified.append(enriched)
    return classified


async def _classify_sources(
    sources: list[dict[str, Any]],
    *,
    symbol: str,
    company_name: str,
    aliases: list[str],
) -> list[dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    for item in sources[:5]:
        text = " ".join(filter(None, [str(item.get("title", "")).strip(), str(item.get("content", "")).strip()]))
        classification = await _classify_text(
            text,
            symbol=symbol,
            company_name=company_name,
            aliases=aliases,
        )
        normalized = _format_source(item)
        normalized["classification"] = classification.model_dump()
        classified.append(normalized)
    return classified


def _aggregate_social_score(posts: list[dict[str, Any]]) -> tuple[float, float, int]:
    weighted_sum = 0.0
    total_weight = 0.0
    bullish_weight = 0.0
    bearish_weight = 0.0
    relevant_count = 0

    for item in posts:
        classification = item.get("classification", {}) or {}
        label = str(classification.get("label", "irrelevant"))
        if label == "irrelevant":
            continue
        sign = _sentiment_sign(label)
        weight = float(item.get("weight", 0.0) or 0.0)
        relevant_count += 1
        total_weight += weight
        weighted_sum += sign * weight
        if sign > 0:
            bullish_weight += weight
        elif sign < 0:
            bearish_weight += weight

    if total_weight <= 0:
        return 0.0, 0.0, relevant_count

    social_score = _clip(100.0 * (weighted_sum / total_weight), -100.0, 100.0)
    controversy_penalty = min(20.0, 40.0 * min(bullish_weight, bearish_weight) / total_weight)
    return round(social_score, 4), round(controversy_penalty, 4), relevant_count


def _compute_news_adjustment(sources: list[dict[str, Any]]) -> tuple[float, int]:
    weighted_sum = 0.0
    total_weight = 0.0
    valid_count = 0

    for item in sources:
        classification = item.get("classification", {}) or {}
        label = str(classification.get("label", "irrelevant"))
        if label == "irrelevant":
            continue
        sign = _sentiment_sign(label)
        confidence = float(classification.get("confidence", 0.0) or 0.0)
        weight = max(float(item.get("score", 0.0) or 0.0), 0.25) * confidence
        weighted_sum += sign * weight
        total_weight += weight
        valid_count += 1

    if total_weight <= 0:
        return 0.0, valid_count

    adjustment = _clip(15.0 * (weighted_sum / total_weight), -15.0, 15.0)
    return round(adjustment, 4), valid_count


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


async def score_symbol_signal(
    session: AsyncSession,
    *,
    symbol: str,
    keywords: Iterable[str] = (),
    hours: int = DEFAULT_SOCIAL_LOOKBACK_HOURS,
    lang: str = DEFAULT_SOCIAL_LANG,
    execute: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    query_profile = await build_query_profile(
        normalized_symbol,
        keywords=keywords,
        hours=hours,
        lang=lang,
    )
    aliases = _build_company_aliases(normalized_symbol, query_profile["company_name"])
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=int(query_profile["hours"]))
    source_warnings: list[str] = []

    try:
        social_payload = await social_intelligence_service.search_social_posts(
            session,
            provider="x",
            query=query_profile["x_query"],
            limit=DEFAULT_SOCIAL_POST_LIMIT,
            lang=query_profile["lang"],
            min_like_count=0,
            min_repost_count=0,
            exclude_reposts=True,
            exclude_replies=True,
            summarize=False,
            force_refresh=force_refresh,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("X social signal source failed for %s: %s", normalized_symbol, exc)
        social_payload = {"posts": []}
        source_warnings.append(_source_failure_reason("X", exc))

    recent_posts = [
        dict(item)
        for item in social_payload.get("posts", [])
        if _parse_timestamp(item.get("created_at")) >= window_start
    ]
    classified_posts = await _classify_posts(
        recent_posts,
        symbol=normalized_symbol,
        company_name=query_profile["company_name"],
        aliases=aliases,
    )
    classified_posts.sort(key=lambda item: float(item.get("weight", 0.0)), reverse=True)

    try:
        tavily_payload = await tavily_service.search_web(
            query_profile["tavily_query"],
            topic="news",
            max_results=6,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tavily social signal source failed for %s: %s", normalized_symbol, exc)
        tavily_payload = {"results": []}
        source_warnings.append(_source_failure_reason("Tavily", exc))

    classified_sources = await _classify_sources(
        [dict(item) for item in tavily_payload.get("results", [])],
        symbol=normalized_symbol,
        company_name=query_profile["company_name"],
        aliases=aliases,
    )

    social_score, controversy_penalty, relevant_post_count = _aggregate_social_score(classified_posts)
    news_adjustment, valid_source_count = _compute_news_adjustment(classified_sources)
    social_score_adjusted = round(
        _clip(social_score - controversy_penalty + news_adjustment, -100.0, 100.0),
        4,
    )

    trend_map = await monitoring_service.fetch_trend_snapshots([normalized_symbol], force_refresh=force_refresh)
    trend = trend_map.get(
        normalized_symbol,
        monitoring_service._empty_trend_snapshot(normalized_symbol, now),  # noqa: SLF001
    )
    market_score = _compute_market_score(trend)

    positions_map = await _load_positions_map()
    has_position = normalized_symbol in positions_map
    final_weight = round(
        _clip((0.60 * market_score) + (0.40 * social_score_adjusted), -100.0, 100.0),
        4,
    )
    action = _map_action(final_weight, has_position=has_position)

    avg_post_confidence = (
        sum(float((item.get("classification", {}) or {}).get("confidence", 0.0) or 0.0) for item in classified_posts)
        / max(len(classified_posts), 1)
    )
    avg_source_confidence = (
        sum(float((item.get("classification", {}) or {}).get("confidence", 0.0) or 0.0) for item in classified_sources)
        / max(len(classified_sources), 1)
    )
    confidence = _clip(
        0.35
        + min(relevant_post_count, 10) * 0.03
        + min(valid_source_count, 5) * 0.04
        + (avg_post_confidence * 0.18)
        + (avg_source_confidence * 0.12),
        0.0,
        0.95,
    )
    confidence_label = _classify_confidence_label(confidence)
    reasons = [
        f"社媒评分 {social_score_adjusted:+.2f}，其中争议惩罚 {controversy_penalty:.2f}，新闻修正 {news_adjustment:+.2f}。",
        f"行情评分 {market_score:+.2f}，最终权重 {final_weight:+.2f}。",
        f"相关帖子 {relevant_post_count} 条，有效新闻来源 {valid_source_count} 条。",
    ]
    reasons.extend(source_warnings)

    if relevant_post_count < 5 and valid_source_count < 3:
        action = _downgrade_action(action)
        confidence = min(confidence, 0.59)
        confidence_label = "low"
        reasons.append("当前社媒与新闻样本量偏少，信号已降级为观察级别。")

    executed = False
    executed_order_id = None
    execution_message = ""
    if execute:
        try:
            executed, executed_order_id, execution_message = await _execute_signal_if_allowed(
                session,
                symbol=normalized_symbol,
                action=action,
                confidence=confidence,
                confidence_label=confidence_label,
                has_position=has_position,
                final_weight=final_weight,
            )
        except Exception as exc:
            execution_message = str(exc)
    elif action in {"buy", "sell", "reduce_or_sell"}:
        execution_message = "当前仅生成信号，未执行自动交易。"

    snapshot = SocialSignalSnapshot(
        symbol=normalized_symbol,
        snapshot_at=now,
        query_profile_json=json.dumps(query_profile, ensure_ascii=False, default=_json_default),
        social_score=social_score_adjusted,
        market_score=market_score,
        final_weight=final_weight,
        action=action,
        confidence=round(confidence, 4),
        confidence_label=confidence_label,
        reasons_json=json.dumps(reasons, ensure_ascii=False),
        top_posts_json=json.dumps(classified_posts[:5], ensure_ascii=False, default=_json_default),
        top_sources_json=json.dumps(
            [_format_source(item) for item in classified_sources[:5]],
            ensure_ascii=False,
            default=_json_default,
        ),
        executed=executed,
        executed_at=now if executed else None,
        executed_order_id=executed_order_id,
        execution_message=execution_message,
    )
    session.add(snapshot)
    await session.commit()

    return _serialize_snapshot(snapshot)


async def get_latest_signals(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    statement = select(SocialSignalSnapshot).order_by(
        desc(SocialSignalSnapshot.snapshot_at),
        desc(SocialSignalSnapshot.id),
    )
    normalized_symbol = _normalize_symbol(symbol) if symbol else None
    if normalized_symbol:
        statement = statement.where(SocialSignalSnapshot.symbol == normalized_symbol)
        result = await session.execute(statement.limit(max(1, min(limit, 100))))
        return [_serialize_snapshot(item) for item in result.scalars().all()]

    result = await session.execute(statement.limit(max(50, min(limit * 5, 200))))
    latest_by_symbol: dict[str, SocialSignalSnapshot] = {}
    for item in result.scalars().all():
        if item.symbol in latest_by_symbol:
            continue
        latest_by_symbol[item.symbol] = item
        if len(latest_by_symbol) >= max(1, min(limit, 100)):
            break
    return [_serialize_snapshot(item) for item in latest_by_symbol.values()]


async def run_social_monitor(
    session: AsyncSession,
    *,
    symbols: Iterable[str] = (),
    keywords: Iterable[str] = (),
    include_watchlist: bool = True,
    include_positions: bool = True,
    include_candidates: bool = True,
    hours: int = DEFAULT_SOCIAL_LOOKBACK_HOURS,
    lang: str = DEFAULT_SOCIAL_LANG,
    execute: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    seed_symbols = monitoring_service._normalize_symbols(symbols)  # noqa: SLF001
    auto_symbols = await _load_signal_context_symbols(
        session,
        include_watchlist=include_watchlist,
        include_positions=include_positions,
        include_candidates=include_candidates,
        force_refresh=force_refresh,
    )
    ordered_symbols = monitoring_service._normalize_symbols(seed_symbols + auto_symbols)  # noqa: SLF001

    results: list[dict[str, Any]] = []
    for current_symbol in ordered_symbols:
        try:
            result = await score_symbol_signal(
                session,
                symbol=current_symbol,
                keywords=keywords,
                hours=hours,
                lang=lang,
                execute=execute,
                force_refresh=force_refresh,
            )
            results.append(result)
        except Exception as exc:
            logger.exception("Social signal scoring failed for %s", current_symbol)
            results.append(
                {
                    "symbol": current_symbol,
                    "generated_at": datetime.now(timezone.utc),
                    "query_profile": {
                        "symbol": current_symbol,
                        "company_name": current_symbol,
                        "keywords": _normalize_keywords(keywords),
                        "context_terms": list(_DEFAULT_CONTEXT_TERMS),
                        "x_query": current_symbol,
                        "tavily_query": current_symbol,
                        "lang": lang,
                        "hours": hours,
                    },
                    "social_score": 0.0,
                    "market_score": 0.0,
                    "final_weight": 0.0,
                    "action": "hold",
                    "confidence": 0.0,
                    "confidence_label": "low",
                    "reasons": [f"社媒信号生成失败：{exc}"],
                    "top_posts": [],
                    "top_sources": [],
                    "executed": False,
                    "executed_order_id": None,
                    "execution_message": "",
                }
            )

    executed_count = sum(1 for item in results if item.get("executed"))
    return {
        "generated_at": datetime.now(timezone.utc),
        "symbols": results,
        "executed_count": executed_count,
    }
