"""Public entry points: score a symbol, list snapshots, run the monitor loop."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SocialSignalSnapshot
from app.services import (
    monitoring_service,
    social_intelligence_service,
    tavily_service,
)
from app.services.social_signal.classify import (
    _DEFAULT_CONTEXT_TERMS,
    _classify_posts,
    _classify_sources,
)
from app.services.social_signal.local_models import (
    DEFAULT_SOCIAL_LANG,
    DEFAULT_SOCIAL_LOOKBACK_HOURS,
    DEFAULT_SOCIAL_POST_LIMIT,
)
from app.services.social_signal.normalize import (
    _build_company_aliases,
    _clip,
    _format_source,
    _json_default,
    _normalize_keywords,
    _normalize_symbol,
    _parse_timestamp,
    _source_failure_reason,
)
from app.services.social_signal.persistence import (
    _execute_signal_if_allowed,
    _load_positions_map,
    _load_signal_context_symbols,
    build_query_profile,
)
from app.services.social_signal.scoring import (
    _aggregate_social_score,
    _classify_confidence_label,
    _compute_market_score,
    _compute_news_adjustment,
    _downgrade_action,
    _map_action,
    _serialize_snapshot,
)

logger = logging.getLogger(__name__)


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
