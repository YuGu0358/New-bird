from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any

from app import runtime_settings
from app.services.network_utils import run_sync_with_retries

_SEARCH_CACHE_TTL = timedelta(minutes=20)
_search_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}


def _create_client():
    try:
        from tavily import TavilyClient
    except ImportError as exc:
        raise RuntimeError("tavily-python is not installed.") from exc

    api_key = runtime_settings.get_required_setting(
        "TAVILY_API_KEY",
        "Tavily API key is missing. Configure it in the settings page or backend/.env first.",
    )

    return TavilyClient(api_key=api_key)


def _normalize_topic(topic: str | None) -> str:
    normalized = str(topic or "news").strip().lower()
    if normalized not in {"news", "general"}:
        raise ValueError("topic 仅支持 news 或 general。")
    return normalized


def _normalize_result(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    url = str(item.get("url", "")).strip()
    if not url:
        return None

    content = str(item.get("content", "")).strip().replace("\n", " ")
    return {
        "title": str(item.get("title", "")).strip() or url,
        "url": url,
        "content": content[:280].strip(),
        "source": str(item.get("source", "")).strip() or None,
        "domain": str(item.get("domain", "")).strip() or None,
        "published_date": str(item.get("published_date", "")).strip() or None,
        "score": float(item.get("score", 0.0) or 0.0),
    }


async def search_web(query: str, topic: str = "news", max_results: int = 6) -> dict[str, Any]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("搜索关键词不能为空。")

    normalized_topic = _normalize_topic(topic)
    cache_key = (normalized_query.lower(), normalized_topic)
    now = datetime.now(timezone.utc)
    cached_item = _search_cache.get(cache_key)
    if cached_item is not None and now - cached_item[0] <= _SEARCH_CACHE_TTL:
        return cached_item[1]

    client = _create_client()
    response = await run_sync_with_retries(
        client.search,
        query=normalized_query,
        topic=normalized_topic,
        search_depth="advanced",
        max_results=max(1, min(int(max_results), 8)),
        include_answer=True,
    )

    answer = ""
    results: list[dict[str, Any]] = []
    if isinstance(response, dict):
        answer = str(response.get("answer", "")).strip()
        results = [
            normalized_item
            for normalized_item in (
                _normalize_result(item) for item in (response.get("results") or [])
            )
            if normalized_item is not None
        ]

    if not answer:
        answer = f"已完成 Tavily 搜索，但当前没有返回可直接展示的摘要。关键词：{normalized_query}"

    payload = {
        "query": normalized_query,
        "topic": normalized_topic,
        "answer": answer,
        "generated_at": now,
        "results": results,
    }
    _search_cache[cache_key] = (now, payload)
    return payload


async def fetch_news_summary(symbol: str) -> dict[str, Any]:
    client = _create_client()
    normalized_symbol = symbol.upper()
    query = (
        f"Summarize the latest market-moving news for {normalized_symbol}. "
        "Focus on price catalysts, earnings, guidance, regulation, or macro signals."
    )

    response = await run_sync_with_retries(
        client.search,
        query=query,
        topic="news",
        search_depth="advanced",
        max_results=5,
        include_answer=True,
    )

    answer = ""
    sources: list[str] = []

    if isinstance(response, dict):
        answer = str(response.get("answer", "")).strip()
        results = response.get("results", []) or []
        for item in results[:3]:
            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip().replace("\n", " ")
            snippet = content[:180].strip()
            if title and snippet:
                sources.append(f"{title}: {snippet}")
            elif title:
                sources.append(title)

    sections = [section for section in [answer, "\n".join(sources)] if section]
    summary = "\n\n".join(sections).strip()

    if not summary:
        summary = (
            f"No material headlines were returned for {normalized_symbol}. "
            "Re-run the query later or inspect the raw news feed."
        )

    return {
        "symbol": normalized_symbol,
        "summary": summary,
        "source": "Tavily",
    }
