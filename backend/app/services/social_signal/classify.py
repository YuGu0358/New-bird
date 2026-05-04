"""Sentiment / topic classification — local rule-based + optional OpenAI fallback."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from app import runtime_settings
from app.services import openai_service
from app.services.social_signal.local_models import (
    SocialTextClassification,
    _OpenAIClassificationResponse,
)
from app.services.social_signal.normalize import (
    _clip,
    _format_source,
    _parse_timestamp,
)

logger = logging.getLogger(__name__)

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


async def _classify_posts(
    posts: list[dict[str, Any]],
    *,
    symbol: str,
    company_name: str,
    aliases: list[str],
) -> list[dict[str, Any]]:
    # Deferred import to avoid circular dependency with scoring.py.
    from app.services.social_signal.scoring import (
        _author_weight,
        _engagement_weight,
        _recency_weight,
    )

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
