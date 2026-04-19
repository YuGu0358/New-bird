from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from app.services.network_utils import run_sync_with_retries

_PROFILE_CACHE_TTL = timedelta(hours=6)
_profile_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
_PLAIN_CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "HYPE"}


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _download_company_info_sync(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    return dict(ticker.info or {})


def _download_company_search_sync(symbol: str) -> dict[str, Any]:
    query = quote_plus(symbol)
    request = Request(
        f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=5&newsCount=0",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(request, timeout=8) as response:  # noqa: S310 - public market-data endpoint.
        payload = json.loads(response.read().decode("utf-8"))

    return _build_search_profile(symbol, payload.get("quotes", []))


def _build_search_profile(symbol: str, quotes: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").upper()
    selected_item: dict[str, Any] | None = None
    for item in quotes:
        if str(item.get("symbol") or "").upper() == normalized_symbol:
            selected_item = item
            break

    if selected_item is None:
        for item in quotes:
            candidate_symbol = str(item.get("symbol") or "").upper()
            quote_type = str(item.get("quoteType") or "").upper()
            if quote_type == "CRYPTOCURRENCY" and candidate_symbol.startswith(normalized_symbol):
                selected_item = item
                break

    if selected_item is None:
        return {}

    return {
        "longName": selected_item.get("longname") or selected_item.get("shortname"),
        "shortName": selected_item.get("shortname") or selected_item.get("longname"),
        "fullExchangeName": selected_item.get("exchDisp") or selected_item.get("exchange"),
        "exchange": selected_item.get("exchange"),
        "quoteType": selected_item.get("quoteType") or selected_item.get("typeDisp"),
        "sector": selected_item.get("sectorDisp") or selected_item.get("sector"),
        "industry": selected_item.get("industryDisp") or selected_item.get("industry"),
        "symbol": selected_item.get("symbol"),
        "_profile_fallback": True,
    }


def _is_yahoo_profile_auth_error(exc: BaseException) -> bool:
    lowered = str(exc).lower()
    return "401" in lowered or "unauthorized" in lowered


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


def _build_business_summary(info: dict[str, Any], *, fallback_error: BaseException | None = None) -> str:
    summary = _pick_text(
        info,
        "longBusinessSummary",
        "description",
        "longDescription",
        "summary",
    )
    if summary:
        return summary

    if info.get("_profile_fallback"):
        company_name = _pick_text(info, "longName", "shortName", "displayName", "name") or "该标的"
        sector = _pick_text(info, "sector")
        industry = _pick_text(info, "industry")
        detail = " / ".join(item for item in (sector, industry) if item)
        reason = "Yahoo 公司简介接口暂时不可用"
        if fallback_error is not None and _is_yahoo_profile_auth_error(fallback_error):
            reason = "Yahoo 公司简介接口暂时返回未授权"
        if detail:
            return f"{reason}，已改用 Yahoo 搜索结果显示基础资料：{company_name}，分类为 {detail}。"
        return f"{reason}，已改用 Yahoo 搜索结果显示基础资料：{company_name}。"

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

    fallback_error: BaseException | None = None
    info: dict[str, Any] = {}
    if normalized_symbol in _PLAIN_CRYPTO_SYMBOLS:
        try:
            info = await run_sync_with_retries(_download_company_search_sync, normalized_symbol)
        except Exception as exc:  # noqa: BLE001
            fallback_error = exc
            info = {}

    if not info:
        try:
            info = await run_sync_with_retries(_download_company_info_sync, normalized_symbol)
        except Exception as exc:  # noqa: BLE001
            fallback_error = exc
            info = {}

    if not info:
        try:
            info = await run_sync_with_retries(_download_company_search_sync, normalized_symbol)
        except Exception as exc:  # noqa: BLE001
            if fallback_error is None:
                fallback_error = exc
            info = {}

    if not info:
        if fallback_error is not None:
            raise ValueError(
                f"{normalized_symbol} 当前公司资料源暂时不可用，请稍后重试。"
            ) from fallback_error
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
        "business_summary": _build_business_summary(info, fallback_error=fallback_error),
        "generated_at": now,
    }
    _profile_cache[normalized_symbol] = (now, payload)
    return payload
