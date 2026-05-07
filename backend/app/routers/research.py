from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from app.database import NewsCache
from app.dependencies import RequestLang, SessionDep, service_error
from app.models import (
    CompanyProfileResponse,
    CompsTableResponse,
    DcfResponse,
    EarningsReviewRequest,
    EarningsReviewResponse,
    MarketResearchReportResponse,
    MarketResearchRequest,
    NewsArticle,
    NewsClustersResponse,
    PeerRowResponse,
    RawHeadlinesResponse,
    SecEdgarFilingsResponse,
    StockResearchReport,
    SymbolChartResponse,
    TavilySearchResponse,
)
from app.models.chart_annotation import ChartAnnotateRequest, ChartAnnotationResponse
from app.services import (
    chart_annotation_service,
    chart_service,
    company_profile_service,
    market_research_service,
    news_clustering_service,
    research_service,
    sec_edgar_service,
    tavily_service,
    valuation_service,
)
from core.agents import LLMRouterUnavailableError, ResearchAnalyzerParseError

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


@router.get("/news/{symbol}/clusters", response_model=NewsClustersResponse)
async def get_news_clusters(
    symbol: str,
    lang: RequestLang,
    max_results: int = 12,
    k_clusters: int = 4,
) -> NewsClustersResponse:
    """KMeans clustering of raw headlines via OpenAI embeddings."""
    if k_clusters < 1 or k_clusters > 10:
        raise HTTPException(
            status_code=400,
            detail="k_clusters must be between 1 and 10",
        )
    if max_results < 2 or max_results > 30:
        raise HTTPException(
            status_code=400,
            detail="max_results must be between 2 and 30",
        )
    try:
        payload = await news_clustering_service.cluster_headlines(
            symbol,
            max_results=max_results,
            k_clusters=k_clusters,
            lang=lang,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return NewsClustersResponse(**payload)


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


@router.post("/research/chart-annotate/{symbol}", response_model=ChartAnnotationResponse)
async def chart_annotate(symbol: str, body: ChartAnnotateRequest) -> ChartAnnotationResponse:
    range_name = body.range or "3mo"
    try:
        chart = await chart_service.get_symbol_chart(symbol, range_name=range_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc

    bars = chart.get("points") or []
    if not bars:
        raise HTTPException(status_code=404, detail=f"{symbol} 没有可用的走势图数据。")

    bar_dicts = [
        {
            "timestamp": p["timestamp"].isoformat() if hasattr(p["timestamp"], "isoformat") else str(p["timestamp"]),
            "open": p["open"],
            "high": p["high"],
            "low": p["low"],
            "close": p["close"],
            "volume": p["volume"],
        }
        for p in bars
    ]
    try:
        payload = await chart_annotation_service.annotate_chart(
            symbol.upper(), range_name, bar_dicts, body.image_base64
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return ChartAnnotationResponse.model_validate(payload)


@router.get("/company/{symbol}", response_model=CompanyProfileResponse)
async def get_company_profile(symbol: str, lang: RequestLang) -> CompanyProfileResponse:
    try:
        payload = await company_profile_service.get_company_profile(symbol, lang=lang)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return CompanyProfileResponse(**payload)


@router.get(
    "/research/sec-edgar/{symbol}/filings",
    response_model=SecEdgarFilingsResponse,
)
async def get_sec_edgar_filings(
    symbol: str,
    limit: int = 20,
    form_types: str = "10-K,10-Q,8-K",
) -> SecEdgarFilingsResponse:
    """Recent SEC EDGAR filings for `symbol`.

    `form_types` is a comma-separated list (default `10-K,10-Q,8-K`).
    Errors map: unknown ticker → 404, disabled gate / missing UA → 503,
    everything else → 503 via `service_error()`.
    """
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="limit must be between 1 and 100",
        )
    parsed_forms = tuple(
        f.strip().upper() for f in form_types.split(",") if f.strip()
    )
    if not parsed_forms:
        raise HTTPException(
            status_code=400,
            detail="form_types must contain at least one form (e.g. '10-K,10-Q')",
        )

    try:
        payload = await sec_edgar_service.get_recent_filings(
            symbol, form_types=parsed_forms, limit=limit
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return SecEdgarFilingsResponse(**payload)


# ---------------------------------------------------------------------------
# Phase 4 — Research-flavoured endpoints (market, earnings, comps, dcf).
# ---------------------------------------------------------------------------

# Default DCF assumption set used by `/api/research/dcf/{symbol}`. The current
# upstream `/api/valuation/dcf` engine requires user-supplied inputs; for the
# research wrapper we use a conservative deterministic baseline so the
# endpoint is callable without forcing every consumer to compute FCFE first.
_DCF_DEFAULTS: dict[str, float | int] = {
    "fcfe0": 5.0,
    "growth_stage1": 0.08,
    "growth_terminal": 0.025,
    "discount_rate": 0.09,
    "years_stage1": 7,
}


def _research_error(exc: Exception) -> HTTPException:
    """Map research-layer exceptions to HTTP responses (mirrors agents.py)."""
    if isinstance(exc, LLMRouterUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ResearchAnalyzerParseError):
        return HTTPException(status_code=502, detail=f"Upstream parse error: {exc}")
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        # disabled gates / missing config => surface as 503
        return HTTPException(status_code=503, detail=str(exc))
    return service_error(exc)


def _market_research_to_response(report: object) -> MarketResearchReportResponse:
    """Convert a `MarketResearchReport` dataclass into its Pydantic mirror."""
    from dataclasses import asdict

    return MarketResearchReportResponse(**asdict(report))  # type: ignore[arg-type]


def _earnings_review_to_response(review: object) -> EarningsReviewResponse:
    """Convert an `EarningsReview` dataclass into its Pydantic mirror."""
    from dataclasses import asdict

    return EarningsReviewResponse(**asdict(review))  # type: ignore[arg-type]


@router.post("/research/market", response_model=MarketResearchReportResponse)
async def post_market_research(
    request: MarketResearchRequest,
) -> MarketResearchReportResponse:
    """Run the market-researcher persona for a sector / theme."""
    try:
        report = await research_service.run_market_research(
            sector=request.sector,
            theme=request.theme,
            peer_count=request.peer_count,
        )
    except Exception as exc:
        raise _research_error(exc) from exc
    return _market_research_to_response(report)


@router.post(
    "/research/earnings/{symbol}",
    response_model=EarningsReviewResponse,
)
async def post_earnings_review(
    symbol: str,
    request: EarningsReviewRequest | None = None,  # body optional
) -> EarningsReviewResponse:
    """Run the earnings-reviewer persona for `symbol`."""
    _ = request  # body is currently empty; reserved for future overrides
    try:
        review = await research_service.run_earnings_review(symbol=symbol)
    except Exception as exc:
        raise _research_error(exc) from exc
    return _earnings_review_to_response(review)


@router.get("/research/comps/{symbol}", response_model=CompsTableResponse)
async def get_comps(symbol: str, n: int = 10) -> CompsTableResponse:
    """Deterministic peer comps — no LLM.

    Pulls the subject's sector via `company_profile_service`, then picks up to
    ``n`` peers (the static fallback universe filtered to the same sector).
    """
    if n < 1 or n > 20:
        raise HTTPException(status_code=400, detail="n must be between 1 and 20")

    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol is required")

    try:
        subject_profile = await company_profile_service.get_company_profile(sym)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc

    sector = (subject_profile or {}).get("sector") or ""
    peer_rows: list[PeerRowResponse] = []

    candidate_universe = research_service._FALLBACK_PEERS  # noqa: SLF001
    for candidate in candidate_universe:
        if candidate == sym:
            continue
        if len(peer_rows) >= n:
            break
        try:
            profile = await company_profile_service.get_company_profile(candidate)
        except Exception:  # noqa: BLE001
            continue
        if not profile:
            continue
        peer_sector = profile.get("sector") or ""
        if sector and peer_sector and peer_sector.lower() != sector.lower():
            continue
        peer_rows.append(
            PeerRowResponse(
                symbol=candidate,
                name=profile.get("company_name"),
                market_cap=profile.get("market_cap"),
                pe_ratio=profile.get("pe_ratio"),
                ev_ebitda=None,
                ps_ratio=None,
                revenue_growth_yoy=None,
                notes=profile.get("industry"),
            )
        )

    return CompsTableResponse(
        symbol=sym,
        peers=peer_rows,
        median_pe=None,
        median_ev_ebitda=None,
        commentary="Deterministic peer comps from sector classification.",
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/research/dcf/{symbol}", response_model=DcfResponse)
async def get_research_dcf(symbol: str) -> DcfResponse:
    """Wrap `/api/valuation/dcf` with a research-flavoured response.

    We do NOT re-implement DCF math — we proxy through
    `valuation_service.compute_dcf` with a conservative default assumption
    set so the endpoint is GET-callable without a body. Callers who need
    fine-grained control should use `/api/valuation/dcf` directly.
    """
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol is required")

    try:
        payload = valuation_service.compute_dcf(
            fcfe0=float(_DCF_DEFAULTS["fcfe0"]),
            growth_stage1=float(_DCF_DEFAULTS["growth_stage1"]),
            growth_terminal=float(_DCF_DEFAULTS["growth_terminal"]),
            discount_rate=float(_DCF_DEFAULTS["discount_rate"]),
            years_stage1=int(_DCF_DEFAULTS["years_stage1"]),
            shares_out=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc

    grid_payload = [
        item if isinstance(item, dict) else dict(item) for item in payload.get("grid", [])
    ]

    return DcfResponse(
        symbol=sym,
        inputs=payload["inputs"],
        fair_value_per_share=payload["fair_value_per_share"],
        fair_low=payload["fair_low"],
        fair_high=payload["fair_high"],
        breakdown=payload["breakdown"],
        grid=grid_payload,
        generated_at=payload["generated_at"],
        source="internal valuation engine",
    )
