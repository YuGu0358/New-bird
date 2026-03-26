from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.network_utils import run_sync_with_retries

_PROFILE_CACHE_TTL = timedelta(hours=6)
_profile_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _download_company_info_sync(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    return dict(ticker.info or {})


def _pick_text(info: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _to_float(value: Any) -> float | None:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    return numeric_value if numeric_value > 0 else None


def _to_int(value: Any) -> int | None:
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        return None
    return numeric_value if numeric_value > 0 else None


def _build_location(info: dict[str, Any]) -> str | None:
    parts = []
    for key in ("city", "state", "country"):
        value = _pick_text(info, key)
        if value and value not in parts:
            parts.append(value)
    if not parts:
        return None
    return ", ".join(parts)


def _build_business_summary(info: dict[str, Any]) -> str:
    summary = _pick_text(
        info,
        "longBusinessSummary",
        "description",
        "longDescription",
        "summary",
    )
    if summary:
        return summary

    category = _pick_text(info, "category")
    fund_family = _pick_text(info, "fundFamily")
    sector = _pick_text(info, "sector")
    industry = _pick_text(info, "industry")
    parts = [item for item in (category, fund_family, sector, industry) if item]
    if parts:
        return f"当前未返回完整公司简介，可参考分类信息：{' / '.join(parts)}。"

    return "当前暂无可用的公司简介或主营业务说明。"


async def get_company_profile(symbol: str) -> dict[str, Any]:
    """Return cached company profile data for a symbol using yfinance."""

    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        raise ValueError("股票代码不能为空。")

    now = datetime.now(timezone.utc)
    cached_item = _profile_cache.get(normalized_symbol)
    if cached_item is not None and now - cached_item[0] <= _PROFILE_CACHE_TTL:
        return cached_item[1]

    info = await run_sync_with_retries(_download_company_info_sync, normalized_symbol)
    if not info:
        raise ValueError(f"{normalized_symbol} 当前没有可用公司资料。")

    company_name = _pick_text(info, "longName", "shortName", "displayName", "name")
    payload = {
        "symbol": normalized_symbol,
        "company_name": company_name or normalized_symbol,
        "exchange": _pick_text(info, "fullExchangeName", "exchange"),
        "quote_type": _pick_text(info, "quoteType"),
        "sector": _pick_text(info, "sector"),
        "industry": _pick_text(info, "industry"),
        "category": _pick_text(info, "category"),
        "fund_family": _pick_text(info, "fundFamily"),
        "website": _pick_text(info, "website"),
        "currency": _pick_text(info, "currency", "financialCurrency"),
        "market_cap": _to_float(info.get("marketCap")),
        "full_time_employees": _to_int(info.get("fullTimeEmployees")),
        "location": _build_location(info),
        "business_summary": _build_business_summary(info),
        "generated_at": now,
    }
    _profile_cache[normalized_symbol] = (now, payload)
    return payload
