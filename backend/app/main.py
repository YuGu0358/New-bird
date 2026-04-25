from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_database
from app.dependencies import SessionDep, service_error
from app.models import (
    BotStatus,
    ControlResponse,
    RuntimeSettingsStatus,
    SettingsUpdateRequest,
    SocialProviderStatus,
    SocialSignalRunRequest,
    SocialSignalRunResponse,
    SocialSignalSnapshotView,
    SocialSearchResponse,
)
from app import runtime_settings
from app.routers import account as account_router
from app.routers import alerts as alerts_router
from app.routers import monitoring as monitoring_router
from app.routers import research as research_router
from app.routers import strategies as strategies_router
from app.services import (
    bot_controller,
    price_alerts_service,
    social_polling_service,
    social_intelligence_service,
    social_signal_service,
)

strategy_profiles_service = strategies_router.strategy_profiles_service

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
app.include_router(monitoring_router.router)
app.include_router(research_router.router)
app.include_router(strategies_router.router)
app.include_router(alerts_router.router)


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


@app.get("/api/social/providers", response_model=list[SocialProviderStatus])
async def get_social_providers() -> list[SocialProviderStatus]:
    payload = social_intelligence_service.list_social_providers()
    return [SocialProviderStatus(**item) for item in payload]


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
