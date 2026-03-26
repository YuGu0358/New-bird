from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app import runtime_settings
from app.services.network_utils import run_sync_with_retries

RESEARCH_CACHE_TTL = timedelta(hours=6)
_research_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

RESEARCH_PROMPT = """Do a comprehensive stock analysis for {ticker} as of {date}:
- Current stock price and recent price performance
- Market capitalization and key financial metrics
- Latest earnings results and guidance
- Recent news and developments
- Analyst ratings, upgrades/downgrades, and price targets
- Key risks and opportunities
- Investment recommendation with reasoning
Focus on all the recent updates about the company.
"""


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


def _get_stock_report_schema() -> dict:
    return {
        "properties": {
            "company_name": {
                "type": "string",
                "description": "The full legal or commonly used name of the company",
            },
            "summary": {
                "type": "string",
                "description": "A comprehensive overview of the stock analysis",
            },
            "current_performance": {
                "type": "string",
                "description": "Recent price performance and trading context",
            },
            "key_insights": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Critical takeaways and notable observations",
            },
            "recommendation": {
                "type": "string",
                "description": "Buy, hold, or sell style recommendation with reasoning",
            },
            "risk_assessment": {
                "type": "string",
                "description": "Key risks affecting the stock",
            },
            "price_outlook": {
                "type": "string",
                "description": "Forward-looking view on the price",
            },
            "market_cap": {
                "type": "number",
                "description": "Total market capitalization in US dollars",
            },
            "pe_ratio": {
                "type": "number",
                "description": "Price-to-earnings ratio",
            },
        },
        "required": [
            "company_name",
            "summary",
            "current_performance",
            "key_insights",
            "recommendation",
            "risk_assessment",
            "price_outlook",
        ],
    }


def _normalize_source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": str(item.get("url", "")).strip(),
        "title": str(item.get("title", "")).strip(),
        "source": (str(item.get("source", "")).strip() or None),
        "domain": (str(item.get("domain", "")).strip() or None),
        "published_date": (str(item.get("published_date", "")).strip() or None),
        "score": float(item.get("score", 0.0) or 0.0),
    }


def _fallback_report(symbol: str, reason: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "symbol": symbol,
        "company_name": symbol,
        "summary": f"Deep research could not be completed for {symbol}. {reason}",
        "current_performance": "Unavailable",
        "key_insights": [],
        "recommendation": "Unavailable",
        "risk_assessment": "Unavailable",
        "price_outlook": "Unavailable",
        "market_cap": None,
        "pe_ratio": None,
        "sources": [],
        "generated_at": now,
        "research_model": "mini",
    }


async def _poll_research(
    client: Any,
    request_id: str,
    *,
    poll_interval: int = 2,
    max_poll_seconds: int = 90,
) -> dict[str, Any]:
    elapsed = 0
    response = await run_sync_with_retries(client.get_research, request_id)

    while response.get("status") not in ("completed", "failed"):
        if elapsed >= max_poll_seconds:
            raise TimeoutError("Tavily research polling timed out.")
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        response = await run_sync_with_retries(client.get_research, request_id)

    if response.get("status") == "failed":
        raise RuntimeError(str(response.get("error", "Tavily research failed.")))

    return response


async def fetch_stock_research(symbol: str, research_model: str = "mini") -> dict[str, Any]:
    normalized_symbol = symbol.upper()
    normalized_model = research_model.lower()
    if normalized_model not in {"mini", "pro"}:
        raise ValueError("research_model must be either 'mini' or 'pro'.")

    cache_key = (normalized_symbol, normalized_model)
    cached = _research_cache.get(cache_key)
    if cached is not None:
        generated_at = cached.get("generated_at")
        if isinstance(generated_at, datetime):
            if datetime.now(timezone.utc) - generated_at <= RESEARCH_CACHE_TTL:
                return cached

    client = _create_client()
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        response = await run_sync_with_retries(
            client.research,
            input=RESEARCH_PROMPT.format(ticker=normalized_symbol, date=current_date),
            output_schema=_get_stock_report_schema(),
            model=normalized_model,
        )

        if isinstance(response, dict) and response.get("request_id"):
            response = await _poll_research(client, str(response["request_id"]))

        content = response.get("content", {}) if isinstance(response, dict) else {}
        sources = response.get("sources", []) if isinstance(response, dict) else []

        report = {
            "symbol": normalized_symbol,
            "company_name": str(content.get("company_name", normalized_symbol)).strip()
            or normalized_symbol,
            "summary": str(content.get("summary", "")).strip()
            or f"Research completed for {normalized_symbol}.",
            "current_performance": str(content.get("current_performance", "")).strip()
            or "Unavailable",
            "key_insights": [
                str(item).strip()
                for item in (content.get("key_insights") or [])
                if str(item).strip()
            ],
            "recommendation": str(content.get("recommendation", "")).strip()
            or "Unavailable",
            "risk_assessment": str(content.get("risk_assessment", "")).strip()
            or "Unavailable",
            "price_outlook": str(content.get("price_outlook", "")).strip()
            or "Unavailable",
            "market_cap": (
                float(content["market_cap"])
                if content.get("market_cap") not in (None, "")
                else None
            ),
            "pe_ratio": (
                float(content["pe_ratio"])
                if content.get("pe_ratio") not in (None, "")
                else None
            ),
            "sources": [
                _normalize_source(item)
                for item in sources
                if isinstance(item, dict) and str(item.get("url", "")).strip()
            ],
            "generated_at": datetime.now(timezone.utc),
            "research_model": normalized_model,
        }
    except Exception as exc:
        report = _fallback_report(normalized_symbol, str(exc))

    _research_cache[cache_key] = report
    return report
