from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import NewsCache, Trade, get_session, init_database
from app.models import (
    Account,
    AssetUniverseItem,
    BotStatus,
    ControlResponse,
    MonitoringOverview,
    NewsArticle,
    OrderRecord,
    Position,
    RuntimeSettingsStatus,
    SettingsUpdateRequest,
    SocialProviderStatus,
    SocialSearchResponse,
    StockResearchReport,
    StrategyAnalysisDraft,
    StrategyAnalysisRequest,
    StrategyLibraryResponse,
    StrategySaveRequest,
    TradeRecord,
    WatchlistUpdateRequest,
)
from app import runtime_settings
from app.services import (
    alpaca_service,
    bot_controller,
    market_research_service,
    monitoring_service,
    social_intelligence_service,
    strategy_profiles_service,
    tavily_service,
)

NEWS_CACHE_TTL = timedelta(hours=4)
FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
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

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _service_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@app.on_event("startup")
async def startup_event() -> None:
    await init_database()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await bot_controller.shutdown_bot()


@app.get("/api/account", response_model=Account)
async def get_account() -> Account:
    try:
        payload = await alpaca_service.get_account()
    except Exception as exc:
        raise _service_error(exc) from exc
    return Account(**payload)


@app.get("/api/positions", response_model=list[Position])
async def get_positions() -> list[Position]:
    try:
        payload = await alpaca_service.list_positions()
    except Exception as exc:
        raise _service_error(exc) from exc
    return [Position(**row) for row in payload]


@app.get("/api/trades", response_model=list[TradeRecord])
async def get_trades(session: SessionDep) -> list[TradeRecord]:
    result = await session.execute(
        select(Trade).order_by(desc(Trade.exit_date), desc(Trade.id))
    )
    trades = result.scalars().all()
    return [TradeRecord.model_validate(item) for item in trades]


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
        cached_at = _normalize_timestamp(cached_item.timestamp)
        if datetime.now(timezone.utc) - cached_at <= NEWS_CACHE_TTL:
            return NewsArticle.model_validate(cached_item)

    try:
        payload = await tavily_service.fetch_news_summary(normalized_symbol)
    except Exception as exc:
        if cached_item is not None:
            return NewsArticle.model_validate(cached_item)
        raise _service_error(exc) from exc

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
        raise _service_error(exc) from exc
    return StockResearchReport(**payload)


@app.get("/api/orders", response_model=list[OrderRecord])
async def get_orders(status: str = "all") -> list[OrderRecord]:
    try:
        payload = await alpaca_service.list_orders(status=status)
    except Exception as exc:
        raise _service_error(exc) from exc
    return [OrderRecord(**row) for row in payload]


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
        raise _service_error(exc) from exc
    return MonitoringOverview(**payload)


@app.get("/api/universe", response_model=list[AssetUniverseItem])
async def get_universe(
    query: str = "",
    limit: int = 50,
) -> list[AssetUniverseItem]:
    try:
        payload = await monitoring_service.search_alpaca_universe(query=query, limit=limit)
    except Exception as exc:
        raise _service_error(exc) from exc
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
        raise _service_error(exc) from exc


@app.delete("/api/watchlist/{symbol}", response_model=list[str])
async def remove_watchlist_symbol(
    symbol: str,
    session: SessionDep,
) -> list[str]:
    try:
        return await monitoring_service.remove_watchlist_symbol(session, symbol)
    except Exception as exc:
        raise _service_error(exc) from exc


@app.post("/api/monitoring/refresh", response_model=MonitoringOverview)
async def refresh_monitoring(session: SessionDep) -> MonitoringOverview:
    try:
        payload = await monitoring_service.get_monitoring_overview(
            session,
            force_refresh=True,
        )
    except Exception as exc:
        raise _service_error(exc) from exc
    return MonitoringOverview(**payload)


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
        raise _service_error(exc) from exc
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
        raise _service_error(exc) from exc
    return StrategyLibraryResponse(**payload)


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
        raise _service_error(exc) from exc
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
        raise _service_error(exc) from exc
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
        raise _service_error(exc) from exc
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
        raise _service_error(exc) from exc
    return SocialSearchResponse(**payload)


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


@app.post("/api/orders/cancel", response_model=ControlResponse)
async def cancel_orders() -> ControlResponse:
    try:
        cancelled_count = await alpaca_service.cancel_all_orders()
    except Exception as exc:
        raise _service_error(exc) from exc

    return ControlResponse(
        success=True,
        message=f"已提交撤销挂单请求，共处理 {cancelled_count} 笔订单。",
    )


@app.post("/api/positions/close", response_model=ControlResponse)
async def close_positions() -> ControlResponse:
    try:
        submitted_count = await alpaca_service.close_all_positions()
    except Exception as exc:
        raise _service_error(exc) from exc

    return ControlResponse(
        success=True,
        message=f"已提交全部平仓请求，共处理 {submitted_count} 个持仓。",
    )


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
    if requested_path.exists() and requested_path.is_file() and FRONTEND_DIST_DIR in requested_path.parents:
        return FileResponse(requested_path)

    index_file = FRONTEND_DIST_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend build is missing. Run npm run build.")
    return FileResponse(index_file)
