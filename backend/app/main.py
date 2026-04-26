from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_database
from app.routers import account as account_router
from app.routers import alerts as alerts_router
from app.routers import bot as bot_router
from app.routers import monitoring as monitoring_router
from app.routers import research as research_router
from app.routers import settings as settings_router
from app.routers import social as social_router
from app.routers import strategies as strategies_router
from app.services import (
    bot_controller,
    price_alerts_service,
    social_polling_service,
)

FRONTEND_DIST_DIR = Path(
    os.getenv(
        "TRADING_PLATFORM_FRONTEND_DIST",
        str(Path(__file__).resolve().parents[2] / "frontend" / "dist"),
    )
).expanduser().resolve()
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown sequence (replaces deprecated @app.on_event).

    Tests bypass this by constructing TestClient(app) without `with`.
    """
    await init_database()
    await price_alerts_service.start_monitor()
    await social_polling_service.start_monitor()
    try:
        yield
    finally:
        await price_alerts_service.shutdown_monitor()
        await social_polling_service.shutdown_monitor()
        await bot_controller.shutdown_bot()


app = FastAPI(
    title="Personal Automated Trading Platform",
    version="1.0.0",
    lifespan=lifespan,
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
app.include_router(social_router.router)
app.include_router(bot_router.router)
app.include_router(settings_router.router)


def _is_safe_frontend_path(base_dir: Path, requested_path: Path) -> bool:
    try:
        requested_path.relative_to(base_dir)
    except ValueError:
        return False
    return True


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
