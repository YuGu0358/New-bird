from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, select

from app.database import NewsCache, init_database
from app.dependencies import SessionDep, service_error
from app.models import (
    AssetUniverseItem,
    BotStatus,
    CompanyProfileResponse,
    ControlResponse,
    MonitoringOverview,
    NewsArticle,
    PriceAlertRuleCreateRequest,
    PriceAlertRuleUpdateRequest,
    PriceAlertRuleView,
    QuantBrainFactorAnalysisRequest,
    RuntimeSettingsStatus,
    SettingsUpdateRequest,
    SocialProviderStatus,
    SocialSignalRunRequest,
    SocialSignalRunResponse,
    SocialSignalSnapshotView,
    SocialSearchResponse,
    StockResearchReport,
    StrategyAnalysisDraft,
    StrategyAnalysisRequest,
    StrategyLibraryResponse,
    StrategyPreviewRequest,
    StrategyPreviewResponse,
    StrategySaveRequest,
    SymbolChartResponse,
    TavilySearchResponse,
    WatchlistUpdateRequest,
)
from app import runtime_settings
from app.routers import account as account_router
from app.services import (
    bot_controller,
    chart_service,
    company_profile_service,
    market_research_service,
    monitoring_service,
    price_alerts_service,
    quantbrain_factor_service,
    social_polling_service,
    social_intelligence_service,
    social_signal_service,
    strategy_profiles_service,
    tavily_service,
)
from app.services import strategy_document_service

NEWS_CACHE_TTL = timedelta(hours=4)
FRONTEND_DIST_DIR = Path(
    os.getenv(
        "TRADING_PLATFORM_FRONTEND_DIST",
        str(Path(__file__).resolve().parents[2] / "frontend" / "dist"),
    )
).expanduser().resolve()
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"

app = FastAPI(
    title="Personal Automated Trading Platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="assets")


app.include_router(account_router.router)


def _is_safe_frontend_path(base_dir: Path, requested_path: Path) -> bool:
    try:
        requested_path.relative_to(base_dir)
    except ValueError:
        return False
    return True


@app.on_event("startup")
async def startup_event() -> None:
    await init_database()
    await price_alerts_service.start_monitor()
    await social_polling_service.start_monitor()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await price_alerts_service.shutdown_monitor()
    await social_polling_service.shutdown_monitor()
    await bot_controller.shutdown_bot()


@app.get("/api/news/{symbol}", response_model=NewsArticle)
async def get_news(symbol: str, session: SessionDep) -> NewsArticle:
    normalized_symbol = symbol.upper()
    result = await session.execute(
        select(NewsCache)
        .where(NewsCache.symbol == normalized_symbol)
        .order_by(desc(NewsCache.timestamp), desc(NewsCache.id))
        .limit(1)
    )
    cached_item = result.scalars().first()

    if cached_item is not None:
        cached_at = account_router._normalize_timestamp(cached_item.timestamp)
        if datetime.now(timezone.utc) - cached_at <= NEWS_CACHE_TTL:
            return NewsArticle.model_validate(cached_item)

    try:
        payload = await tavily_service.fetch_news_summary(normalized_symbol)
    except Exception as exc:
        if cached_item is not None:
            return NewsArticle.model_validate(cached_item)
        raise service_error(exc) from exc

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


@app.get("/api/research/{symbol}", response_model=StockResearchReport)
async def get_stock_research(symbol: str, research_model: str = "mini") -> StockResearchReport:
    try:
        payload = await market_research_service.fetch_stock_research(symbol, research_model)
    except Exception as exc:
        raise service_error(exc) from exc
    return StockResearchReport(**payload)


@app.get("/api/tavily/search", response_model=TavilySearchResponse)
async def search_with_tavily(
    query: str,
    topic: str = "news",
    max_results: int = 6,
) -> TavilySearchResponse:
    try:
        payload = await tavily_service.search_web(
            query=query,
            topic=topic,
            max_results=max_results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return TavilySearchResponse(**payload)


@app.get("/api/monitoring", response_model=MonitoringOverview)
async def get_monitoring_overview(
    session: SessionDep,
    force_refresh: bool = False,
) -> MonitoringOverview:
    try:
        payload = await monitoring_service.get_monitoring_overview(
            session,
            force_refresh=force_refresh,
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return MonitoringOverview(**payload)


@app.get("/api/chart/{symbol}", response_model=SymbolChartResponse)
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


@app.get("/api/company/{symbol}", response_model=CompanyProfileResponse)
async def get_company_profile(symbol: str) -> CompanyProfileResponse:
    try:
        payload = await company_profile_service.get_company_profile(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return CompanyProfileResponse(**payload)


@app.get("/api/universe", response_model=list[AssetUniverseItem])
async def get_universe(
    query: str = "",
    limit: int = 50,
) -> list[AssetUniverseItem]:
    try:
        payload = await monitoring_service.search_alpaca_universe(query=query, limit=limit)
    except Exception as exc:
        raise service_error(exc) from exc
    return [AssetUniverseItem(**row) for row in payload]


@app.post("/api/watchlist", response_model=list[str])
async def add_watchlist_symbol(
    request: WatchlistUpdateRequest,
    session: SessionDep,
) -> list[str]:
    try:
        return await monitoring_service.add_watchlist_symbol(session, request.symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@app.delete("/api/watchlist/{symbol}", response_model=list[str])
async def remove_watchlist_symbol(
    symbol: str,
    session: SessionDep,
) -> list[str]:
    try:
        return await monitoring_service.remove_watchlist_symbol(session, symbol)
    except Exception as exc:
        raise service_error(exc) from exc


@app.post("/api/monitoring/refresh", response_model=MonitoringOverview)
async def refresh_monitoring(session: SessionDep) -> MonitoringOverview:
    try:
        payload = await monitoring_service.get_monitoring_overview(
            session,
            force_refresh=True,
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return MonitoringOverview(**payload)


@app.get("/api/alerts", response_model=list[PriceAlertRuleView])
async def get_price_alert_rules(
    session: SessionDep,
    symbol: str | None = None,
) -> list[PriceAlertRuleView]:
    try:
        payload = await price_alerts_service.list_rules(session, symbol=symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return [PriceAlertRuleView(**item) for item in payload]


@app.post("/api/alerts", response_model=PriceAlertRuleView)
async def create_price_alert_rule(
    request: PriceAlertRuleCreateRequest,
    session: SessionDep,
) -> PriceAlertRuleView:
    try:
        payload = await price_alerts_service.create_rule(session, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PriceAlertRuleView(**payload)


@app.patch("/api/alerts/{rule_id}", response_model=PriceAlertRuleView)
async def update_price_alert_rule(
    rule_id: int,
    request: PriceAlertRuleUpdateRequest,
    session: SessionDep,
) -> PriceAlertRuleView:
    try:
        payload = await price_alerts_service.update_rule(session, rule_id, request)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "没有找到" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PriceAlertRuleView(**payload)


@app.delete("/api/alerts/{rule_id}", response_model=ControlResponse)
async def delete_price_alert_rule(
    rule_id: int,
    session: SessionDep,
) -> ControlResponse:
    try:
        await price_alerts_service.delete_rule(session, rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return ControlResponse(success=True, message="提醒规则已删除。")


@app.get("/api/social/providers", response_model=list[SocialProviderStatus])
async def get_social_providers() -> list[SocialProviderStatus]:
    payload = social_intelligence_service.list_social_providers()
    return [SocialProviderStatus(**item) for item in payload]


@app.get("/api/strategies", response_model=StrategyLibraryResponse)
async def get_strategy_library(session: SessionDep) -> StrategyLibraryResponse:
    payload = await strategy_profiles_service.list_strategies(session)
    return StrategyLibraryResponse(**payload)


@app.post("/api/strategies/analyze", response_model=StrategyAnalysisDraft)
async def analyze_strategy(request: StrategyAnalysisRequest) -> StrategyAnalysisDraft:
    try:
        payload = await strategy_profiles_service.analyze_strategy(request.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyAnalysisDraft(**payload.model_dump())


@app.post("/api/strategies/analyze-upload", response_model=StrategyAnalysisDraft)
async def analyze_strategy_with_files(
    description: str = Form(""),
    files: list[UploadFile] | None = File(None),
) -> StrategyAnalysisDraft:
    try:
        payloads: list[tuple[str, bytes]] = []
        for file in files or []:
            payloads.append((file.filename or "strategy-note.txt", await file.read()))
        documents = strategy_document_service.extract_strategy_documents(payloads)
        payload = await strategy_profiles_service.analyze_strategy(description, documents)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyAnalysisDraft(**payload.model_dump())


@app.post("/api/strategies/analyze-factor-code", response_model=StrategyAnalysisDraft)
async def analyze_quantbrain_factor_code(
    request: QuantBrainFactorAnalysisRequest,
) -> StrategyAnalysisDraft:
    try:
        payload = await strategy_profiles_service.analyze_factor_code_strategy(
            request.code,
            description=request.description,
            source_name=request.source_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyAnalysisDraft(**payload.model_dump())


@app.post("/api/strategies/analyze-factor-upload", response_model=StrategyAnalysisDraft)
async def analyze_quantbrain_factor_upload(
    description: str = Form(""),
    code: str = Form(""),
    files: list[UploadFile] | None = File(None),
) -> StrategyAnalysisDraft:
    try:
        payloads: list[tuple[str, bytes]] = []
        for file in files or []:
            payloads.append((file.filename or "quantbrain-factor.py", await file.read()))
        documents = quantbrain_factor_service.extract_factor_code_files(payloads)
        code_sections = []
        if str(code or "").strip():
            code_sections.append(f"# Source: pasted-quantbrain-factor.py\n{code.strip()}")
        code_sections.extend(f"# Source: {item['name']}\n{item['code']}" for item in documents)
        combined_code = "\n\n".join(code_sections)
        source_names = ["pasted-quantbrain-factor.py"] if str(code or "").strip() else []
        source_names.extend(item["name"] for item in documents)
        source_name = ", ".join(source_names)
        payload = await strategy_profiles_service.analyze_factor_code_strategy(
            combined_code,
            description=description,
            source_name=source_name or "uploaded-factor.py",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyAnalysisDraft(**payload.model_dump())


@app.post("/api/strategies", response_model=StrategyLibraryResponse)
async def save_strategy(
    request: StrategySaveRequest,
    session: SessionDep,
) -> StrategyLibraryResponse:
    try:
        payload = await strategy_profiles_service.save_strategy(session, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyLibraryResponse(**payload)


@app.put("/api/strategies/{strategy_id}", response_model=StrategyLibraryResponse)
async def update_strategy(
    strategy_id: int,
    request: StrategySaveRequest,
    session: SessionDep,
) -> StrategyLibraryResponse:
    try:
        payload = await strategy_profiles_service.update_strategy(session, strategy_id, request)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "没有找到" in message else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyLibraryResponse(**payload)


@app.post("/api/strategies/preview", response_model=StrategyPreviewResponse)
async def preview_strategy(request: StrategyPreviewRequest) -> StrategyPreviewResponse:
    try:
        payload = await strategy_profiles_service.preview_strategy(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyPreviewResponse(**payload)


@app.post("/api/strategies/{strategy_id}/activate", response_model=StrategyLibraryResponse)
async def activate_strategy(
    strategy_id: int,
    session: SessionDep,
) -> StrategyLibraryResponse:
    try:
        payload = await strategy_profiles_service.activate_strategy(session, strategy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyLibraryResponse(**payload)


@app.delete("/api/strategies/{strategy_id}", response_model=StrategyLibraryResponse)
async def delete_strategy(
    strategy_id: int,
    session: SessionDep,
) -> StrategyLibraryResponse:
    try:
        payload = await strategy_profiles_service.delete_strategy(session, strategy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return StrategyLibraryResponse(**payload)


@app.get("/api/settings/status", response_model=RuntimeSettingsStatus)
async def get_runtime_settings_status() -> RuntimeSettingsStatus:
    return RuntimeSettingsStatus(**runtime_settings.get_settings_status())


@app.put("/api/settings", response_model=RuntimeSettingsStatus)
async def update_runtime_settings(request: SettingsUpdateRequest) -> RuntimeSettingsStatus:
    try:
        payload = runtime_settings.save_settings(
            request.settings,
            admin_token=request.admin_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return RuntimeSettingsStatus(**payload)


@app.get("/api/social/search", response_model=SocialSearchResponse)
async def search_social(
    session: SessionDep,
    query: str,
    provider: str = "x",
    limit: int = 20,
    lang: str | None = None,
    min_like_count: int = 0,
    min_repost_count: int = 0,
    exclude_reposts: bool = True,
    exclude_replies: bool = True,
    exclude_terms: list[str] | None = None,
    summarize: bool = False,
    force_refresh: bool = False,
) -> SocialSearchResponse:
    try:
        payload = await social_intelligence_service.search_social_posts(
            session,
            provider=provider,
            query=query,
            limit=limit,
            lang=lang,
            min_like_count=min_like_count,
            min_repost_count=min_repost_count,
            exclude_reposts=exclude_reposts,
            exclude_replies=exclude_replies,
            exclude_terms=exclude_terms or (),
            summarize=summarize,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return SocialSearchResponse(**payload)


@app.get("/api/social/score", response_model=SocialSignalSnapshotView)
async def score_social_signal(
    session: SessionDep,
    symbol: str,
    keyword: list[str] | None = None,
    hours: int = 6,
    lang: str = "en",
    execute: bool = False,
    force_refresh: bool = False,
) -> SocialSignalSnapshotView:
    try:
        payload = await social_signal_service.score_symbol_signal(
            session,
            symbol=symbol,
            keywords=keyword or (),
            hours=hours,
            lang=lang,
            execute=execute,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return SocialSignalSnapshotView(**payload)


@app.get("/api/social/signals", response_model=list[SocialSignalSnapshotView])
async def get_social_signals(
    session: SessionDep,
    symbol: str | None = None,
    limit: int = 25,
) -> list[SocialSignalSnapshotView]:
    try:
        payload = await social_signal_service.get_latest_signals(
            session,
            symbol=symbol,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return [SocialSignalSnapshotView(**item) for item in payload]


@app.post("/api/social/run", response_model=SocialSignalRunResponse)
async def run_social_signals(
    request: SocialSignalRunRequest,
    session: SessionDep,
) -> SocialSignalRunResponse:
    try:
        payload = await social_signal_service.run_social_monitor(
            session,
            symbols=request.symbols,
            keywords=request.keywords,
            include_watchlist=request.include_watchlist,
            include_positions=request.include_positions,
            include_candidates=request.include_candidates,
            hours=request.hours,
            lang=request.lang,
            execute=request.execute,
            force_refresh=request.force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return SocialSignalRunResponse(**payload)


@app.get("/api/bot/status", response_model=BotStatus)
async def get_bot_status() -> BotStatus:
    return BotStatus(**await bot_controller.get_status())


@app.post("/api/bot/start", response_model=ControlResponse)
async def start_bot() -> ControlResponse:
    status = await bot_controller.start_bot()
    message = "机器人已启动。" if status["is_running"] else "机器人启动失败。"
    return ControlResponse(success=status["is_running"], message=message)


@app.post("/api/bot/stop", response_model=ControlResponse)
async def stop_bot() -> ControlResponse:
    status = await bot_controller.stop_bot()
    message = "机器人已停止。" if not status["is_running"] else "机器人仍在运行。"
    return ControlResponse(success=not status["is_running"], message=message)


@app.get("/", include_in_schema=False)
async def serve_frontend_index() -> FileResponse:
    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend build is missing. Run npm run build.")
    return FileResponse(index_file)


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend_app(full_path: str) -> FileResponse:
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found.")

    requested_path = (FRONTEND_DIST_DIR / full_path).resolve()
    if (
        requested_path.exists()
        and requested_path.is_file()
        and _is_safe_frontend_path(FRONTEND_DIST_DIR, requested_path)
    ):
        return FileResponse(requested_path)

    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend build is missing. Run npm run build.")
    return FileResponse(index_file)
