from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import runtime_settings
from app.database import SocialSearchCache
from app.services.social_providers import (
    SocialProvider,
    SocialSearchOptions,
    XSocialProvider,
    XiaohongshuSocialProvider,
)

_SOCIAL_CACHE_TTL = timedelta(minutes=15)
_QUERY_TOKEN_PATTERN = re.compile(r'"[^"]+"|\S+')


def _get_provider(provider_name: str) -> SocialProvider:
    normalized = str(provider_name or "x").strip().lower()
    providers: dict[str, SocialProvider] = {
        "x": XSocialProvider(),
        "xiaohongshu": XiaohongshuSocialProvider(),
    }
    provider = providers.get(normalized)
    if provider is None:
        raise ValueError(f"Unsupported social provider: {provider_name}")
    return provider


def list_social_providers() -> list[dict[str, Any]]:
    """Return supported providers and their configuration status."""

    providers: list[SocialProvider] = [XSocialProvider(), XiaohongshuSocialProvider()]
    return [
        {
            "name": provider.name,
            "supported": provider.name in {"x", "xiaohongshu"},
            "configured": provider.is_configured(),
            "note": provider.status_note(),
        }
        for provider in providers
    ]


def _normalize_exclude_terms(exclude_terms: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in exclude_terms:
        term = str(item or "").strip().lower()
        if term and term not in normalized:
            normalized.append(term)
    return tuple(normalized)


def _extract_query_keywords(query: str) -> list[str]:
    keywords: list[str] = []
    for token in _QUERY_TOKEN_PATTERN.findall(str(query or "")):
        normalized = token.strip().strip('"').strip("()").strip()
        if not normalized:
            continue
        upper = normalized.upper()
        if upper in {"AND", "OR"}:
            continue
        if normalized.startswith("-") and ":" in normalized:
            continue
        if ":" in normalized and not normalized.startswith(("#", "$", "@")):
            continue
        normalized = normalized.lstrip("#$@").lower()
        if len(normalized) < 2:
            continue
        if normalized not in keywords:
            keywords.append(normalized)
    return keywords


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _compute_post_score(post: dict[str, Any], matched_terms: list[str], now: datetime) -> float:
    metrics = post.get("metrics", {}) or {}
    author = post.get("author", {}) or {}
    created_at = _parse_timestamp(post.get("created_at"))

    like_count = int(metrics.get("like_count", 0) or 0)
    repost_count = int(metrics.get("repost_count", 0) or 0)
    reply_count = int(metrics.get("reply_count", 0) or 0)
    quote_count = int(metrics.get("quote_count", 0) or 0)
    followers_count = int(author.get("followers_count", 0) or 0)

    engagement = like_count + (repost_count * 2.0) + (reply_count * 1.2) + (quote_count * 1.5)
    engagement_score = math.log1p(max(engagement, 0))
    keyword_score = len(matched_terms) * 1.35
    verified_bonus = 0.45 if author.get("verified") else 0.0
    authority_score = min(math.log10(followers_count + 10), 5.0) / 4.0

    age_hours = max((now - created_at).total_seconds() / 3600.0, 0.0)
    recency_score = max(0.0, 2.0 - min(age_hours, 72.0) / 36.0)

    return round(engagement_score + keyword_score + verified_bonus + authority_score + recency_score, 4)


def _filter_and_rank_posts(
    posts: list[dict[str, Any]],
    *,
    query: str,
    limit: int,
    min_like_count: int,
    min_repost_count: int,
    exclude_terms: tuple[str, ...],
) -> list[dict[str, Any]]:
    keywords = _extract_query_keywords(query)
    now = datetime.now(timezone.utc)
    ranked: list[dict[str, Any]] = []

    for item in posts:
        text = str(item.get("text", "")).strip()
        lowered_text = text.lower()
        metrics = item.get("metrics", {}) or {}

        if exclude_terms and any(term in lowered_text for term in exclude_terms):
            continue
        if int(metrics.get("like_count", 0) or 0) < min_like_count:
            continue
        if int(metrics.get("repost_count", 0) or 0) < min_repost_count:
            continue

        matched_terms = [keyword for keyword in keywords if keyword in lowered_text]
        enriched = dict(item)
        enriched["matched_terms"] = matched_terms
        enriched["score"] = _compute_post_score(enriched, matched_terms, now)
        ranked.append(enriched)

    ranked.sort(
        key=lambda item: (
            float(item.get("score", 0.0)),
            int((item.get("metrics", {}) or {}).get("like_count", 0) or 0),
            _parse_timestamp(item.get("created_at")),
        ),
        reverse=True,
    )
    return ranked[:limit]


def _fallback_social_summary(
    query: str,
    posts: list[dict[str, Any]],
    counts: list[dict[str, Any]],
) -> str:
    if not posts:
        return f"围绕“{query}”当前没有筛出符合条件的帖子。"

    top_post = posts[0]
    author = top_post.get("author", {}) or {}
    metrics = top_post.get("metrics", {}) or {}
    total_mentions = sum(int(bucket.get("post_count", 0) or 0) for bucket in counts)
    summary_parts = [f"围绕“{query}”筛出 {len(posts)} 条高相关帖子。"]
    if total_mentions:
        summary_parts.append(f"最近统计窗口内共出现约 {total_mentions} 条相关公开帖子。")
    summary_parts.append(
        (
            f"热度最高的帖子来自 @{author.get('username') or 'unknown'}，"
            f"获得 {int(metrics.get('like_count', 0) or 0)} 赞和 "
            f"{int(metrics.get('repost_count', 0) or 0)} 次转发。"
        )
    )

    matched_terms = [term for post in posts[:5] for term in post.get("matched_terms", [])]
    if matched_terms:
        top_terms = ", ".join(list(dict.fromkeys(matched_terms))[:5])
        summary_parts.append(f"讨论更集中在这些关键词：{top_terms}。")

    return " ".join(summary_parts)


def _create_openai_client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai is not installed.") from exc

    api_key = runtime_settings.get_required_setting(
        "OPENAI_API_KEY",
        "OPENAI_API_KEY is missing. Configure it in the settings page or backend/.env first.",
    )

    return OpenAI(api_key=api_key)


def _summarize_posts_sync(
    query: str,
    posts: list[dict[str, Any]],
    counts: list[dict[str, Any]],
) -> str:
    client = _create_openai_client()
    model_name = (
        runtime_settings.get_setting(
            "OPENAI_SOCIAL_MODEL",
            runtime_settings.get_setting("OPENAI_CANDIDATE_MODEL", "gpt-4o-2024-08-06")
            or "gpt-4o-2024-08-06",
        )
        or "gpt-4o-2024-08-06"
    )

    rows: list[str] = []
    for index, post in enumerate(posts[:8], start=1):
        author = post.get("author", {}) or {}
        metrics = post.get("metrics", {}) or {}
        text = " ".join(str(post.get("text", "")).split())
        rows.append(
            (
                f"{index}. 作者=@{author.get('username') or 'unknown'} | "
                f"赞={int(metrics.get('like_count', 0) or 0)} | "
                f"转发={int(metrics.get('repost_count', 0) or 0)} | "
                f"分数={float(post.get('score', 0.0)):.2f} | "
                f"内容={text[:320]}"
            )
        )

    count_line = ""
    total_mentions = sum(int(bucket.get("post_count", 0) or 0) for bucket in counts)
    if total_mentions:
        count_line = f"最近统计窗口总量约 {total_mentions} 条。"

    response = client.responses.create(
        model=model_name,
        input=[
            {
                "role": "system",
                "content": (
                    "你是社媒研究助手。请用简体中文总结公开帖子讨论重点，"
                    "只做信息筛选与摘要，不给出自动交易建议。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"查询主题：{query}\n"
                    f"{count_line}\n"
                    "以下是按热度和时效预筛后的帖子：\n"
                    f"{chr(10).join(rows)}\n\n"
                    "请输出一段 4 句以内的中文摘要，说明：\n"
                    "1. 讨论焦点是什么；\n"
                    "2. 哪类观点最受关注；\n"
                    "3. 是否存在明显噪音或低质量内容。"
                ),
            },
        ],
    )
    text = (response.output_text or "").strip()
    if not text:
        raise RuntimeError("OpenAI social summary returned no text.")
    return text


async def _summarize_posts(
    query: str,
    posts: list[dict[str, Any]],
    counts: list[dict[str, Any]],
) -> str:
    if not posts:
        return _fallback_social_summary(query, posts, counts)

    if not runtime_settings.get_setting("OPENAI_API_KEY", ""):
        return _fallback_social_summary(query, posts, counts)

    try:
        return await asyncio.to_thread(_summarize_posts_sync, query, posts, counts)
    except Exception:
        return _fallback_social_summary(query, posts, counts)


def _build_cache_key(options: SocialSearchOptions) -> str:
    payload = {
        "provider": options.provider,
        "query": options.query,
        "limit": options.limit,
        "lang": options.lang,
        "exclude_reposts": options.exclude_reposts,
        "exclude_replies": options.exclude_replies,
        "min_like_count": options.min_like_count,
        "min_repost_count": options.min_repost_count,
        "exclude_terms": list(options.exclude_terms),
        "summarize": options.summarize,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


async def _load_cached_payload(
    session: AsyncSession,
    cache_key: str,
) -> dict[str, Any] | None:
    result = await session.execute(
        select(SocialSearchCache).where(SocialSearchCache.cache_key == cache_key).limit(1)
    )
    cached = result.scalars().first()
    if cached is None:
        return None

    fetched_at = cached.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - fetched_at > _SOCIAL_CACHE_TTL:
        return None

    return json.loads(cached.payload_json)


async def _save_cached_payload(
    session: AsyncSession,
    cache_key: str,
    provider: str,
    query: str,
    payload: dict[str, Any],
) -> None:
    result = await session.execute(
        select(SocialSearchCache).where(SocialSearchCache.cache_key == cache_key).limit(1)
    )
    cached = result.scalars().first()
    serialized = json.dumps(payload, ensure_ascii=False, default=_json_default)

    if cached is None:
        cached = SocialSearchCache(
            cache_key=cache_key,
            provider=provider,
            query=query,
            payload_json=serialized,
        )
        session.add(cached)
    else:
        cached.provider = provider
        cached.query = query
        cached.payload_json = serialized
        cached.fetched_at = datetime.now(timezone.utc)

    await session.commit()


async def search_social_posts(
    session: AsyncSession,
    *,
    provider: str,
    query: str,
    limit: int = 20,
    lang: str | None = None,
    min_like_count: int = 0,
    min_repost_count: int = 0,
    exclude_reposts: bool = True,
    exclude_replies: bool = True,
    exclude_terms: Iterable[str] = (),
    summarize: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Search a social platform, filter the results, and build a digest."""

    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("query is required.")

    options = SocialSearchOptions(
        query=normalized_query,
        provider=str(provider or "x").strip().lower() or "x",
        limit=max(1, min(int(limit), 50)),
        lang=str(lang or "").strip().lower() or None,
        exclude_reposts=exclude_reposts,
        exclude_replies=exclude_replies,
        min_like_count=max(int(min_like_count), 0),
        min_repost_count=max(int(min_repost_count), 0),
        exclude_terms=_normalize_exclude_terms(exclude_terms),
        summarize=summarize,
        force_refresh=force_refresh,
    )

    cache_key = _build_cache_key(options)
    if not options.force_refresh:
        cached = await _load_cached_payload(session, cache_key)
        if cached is not None:
            return cached

    social_provider = _get_provider(options.provider)
    raw_payload = await social_provider.search(options)
    ranked_posts = _filter_and_rank_posts(
        raw_payload.get("posts", []) or [],
        query=options.query,
        limit=options.limit,
        min_like_count=options.min_like_count,
        min_repost_count=options.min_repost_count,
        exclude_terms=options.exclude_terms,
    )
    counts = raw_payload.get("counts", []) or []
    summary = await _summarize_posts(options.query, ranked_posts, counts) if options.summarize else None

    total_results = int(raw_payload.get("total_results", len(ranked_posts)) or len(ranked_posts))
    payload = {
        "provider": options.provider,
        "query": options.query,
        "normalized_query": raw_payload.get("normalized_query", options.query),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": options.limit,
        "lang": options.lang,
        "exclude_reposts": options.exclude_reposts,
        "exclude_replies": options.exclude_replies,
        "min_like_count": options.min_like_count,
        "min_repost_count": options.min_repost_count,
        "exclude_terms": list(options.exclude_terms),
        "summary": summary,
        "returned_results": len(ranked_posts),
        "total_results": total_results,
        "counts": counts,
        "posts": ranked_posts,
        "rate_limit_remaining": raw_payload.get("rate_limit_remaining"),
        "rate_limit_reset": raw_payload.get("rate_limit_reset"),
    }

    await _save_cached_payload(session, cache_key, options.provider, options.query, payload)
    return payload
