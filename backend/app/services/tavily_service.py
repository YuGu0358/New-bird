from __future__ import annotations

import asyncio
from typing import Any

from app import runtime_settings


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


async def fetch_news_summary(symbol: str) -> dict[str, Any]:
    client = _create_client()
    normalized_symbol = symbol.upper()
    query = (
        f"Summarize the latest market-moving news for {normalized_symbol}. "
        "Focus on price catalysts, earnings, guidance, regulation, or macro signals."
    )

    response = await asyncio.to_thread(
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
