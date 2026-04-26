"""Score weights, aggregation, action mapping, market session — pure functions."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.database import SocialSignalSnapshot
from app.services.social_signal.local_models import (
    MARKET_CLOSE_HOUR,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
)
from app.services.social_signal.normalize import _clip


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
