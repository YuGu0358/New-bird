from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from app.database import NewsCache
from app.dependencies import RequestLang, SessionDep, service_error
from app.models import (
    CompanyProfileResponse,
    NewsArticle,
    RawHeadlinesResponse,
    StockResearchReport,
    SymbolChartResponse,
    TavilySearchResponse,
)
from app.services import (
    chart_service,
    company_profile_service,
    market_research_service,
    tavily_service,
)

router = APIRouter(prefix="/api", tags=["research"])

NEWS_CACHE_TTL = timedelta(hours=4)


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.get("/news/{symbol}", response_model=NewsArticle)
async def get_news(symbol: str, session: SessionDep, lang: RequestLang) -> NewsArticle:
    normalized_symbol = symbol.upper()
    # The cached row may be in a different language than the caller requested,
    # so we tag the cache by (symbol, lang). For backward compat we keep the
    # NewsCache table un-touched and just refetch when lang differs from "en".
    cache_eligible = lang == "en"
    cached_item = None
    if cache_eligible:
        result = await session.execute(
            select(NewsCache)
            .where(NewsCache.symbol == normalized_symbol)
            .order_by(desc(NewsCache.timestamp), desc(NewsCache.id))
            .limit(1)
        )
        cached_item = result.scalars().first()

        if cached_item is not None:
            cached_at = _normalize_timestamp(cached_item.timestamp)
            if datetime.now(timezone.utc) - cached_at <= NEWS_CACHE_TTL:
                return NewsArticle.model_validate(cached_item)

    try:
        payload = await tavily_service.fetch_news_summary(normalized_symbol, lang=lang)
    except Exception as exc:
        if cached_item is not None:
            return NewsArticle.model_validate(cached_item)
        raise service_error(exc) from exc

    if cache_eligible:
        news_item = NewsCache(
            symbol=payload["symbol"],
            timestamp=datetime.now(timezone.utc),
            summary=payload["summary"],
            source=payload["source"],
        )
        session.add(news_item)
        await session.commit()
        await session.refresh(news_item)
        return NewsArticle.model_validate(news_item)

    # Non-English: serve directly without persisting to the (English-only)
    # NewsCache table — the in-memory cache inside tavily_service handles
    # repeats per (symbol, lang).
    return NewsArticle(
        symbol=payload["symbol"],
        summary=payload["summary"],
        source=payload["source"],
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/news/{symbol}/headlines", response_model=RawHeadlinesResponse)
async def get_raw_headlines(
    symbol: str,
    lang: RequestLang,
    max_results: int = 10,
) -> RawHeadlinesResponse:
    """Tavily raw headlines for a symbol — no LLM summary."""
    try:
        payload = await tavily_service.fetch_raw_headlines(
            symbol, max_results=max_results, lang=lang
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return RawHeadlinesResponse(**payload)


@router.get("/research/{symbol}", response_model=StockResearchReport)
async def get_stock_research(
    symbol: str,
    lang: RequestLang,
    research_model: str = "mini",
) -> StockResearchReport:
    try:
        payload = await market_research_service.fetch_stock_research(
            symbol, research_model, lang=lang
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return StockResearchReport(**payload)


@router.get("/tavily/search", response_model=TavilySearchResponse)
async def search_with_tavily(
    lang: RequestLang,
    query: str,
    topic: str = "news",
    max_results: int = 6,
) -> TavilySearchResponse:
    try:
        payload = await tavily_service.search_web(
            query=query,
            topic=topic,
            max_results=max_results,
            lang=lang,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return TavilySearchResponse(**payload)


@router.get("/chart/{symbol}", response_model=SymbolChartResponse)
async def get_symbol_chart(
    symbol: str,
    range: str = "3mo",
) -> SymbolChartResponse:
    try:
        payload = await chart_service.get_symbol_chart(symbol, range)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return SymbolChartResponse(**payload)


@router.get("/company/{symbol}", response_model=CompanyProfileResponse)
async def get_company_profile(symbol: str, lang: RequestLang) -> CompanyProfileResponse:
    try:
        payload = await company_profile_service.get_company_profile(symbol, lang=lang)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return CompanyProfileResponse(**payload)
