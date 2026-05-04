"""String / timestamp / numeric normalization helpers (no DB or HTTP)."""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

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
