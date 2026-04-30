from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.observability import configure_logging
from app import scheduler as app_scheduler
from app.database import init_database
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.metrics import HttpMetricsMiddleware
from app.routers import account as account_router
from app.routers import agents as agents_router
from app.routers import alerts as alerts_router
from app.routers import arena as arena_router
from app.routers import backtest as backtest_router
from app.routers import bot as bot_router
from app.routers import broker_accounts as broker_accounts_router
from app.routers import code as code_router
from app.routers import crypto as crypto_router
from app.routers import dbnomics as dbnomics_router
from app.routers import docs as docs_router
from app.routers import geopolitics as geopolitics_router
from app.routers import health as health_router
from app.routers import heatmap as heatmap_router
from app.routers import indicators as indicators_router
from app.routers import journal as journal_router
from app.routers import kraken as kraken_router
from app.routers import macro as macro_router
from app.routers import metrics as metrics_router
from app.routers import monitoring as monitoring_router
from app.routers import onchain as onchain_router
from app.routers import options_chain as options_chain_router
from app.routers import pine_seeds as pine_seeds_router
from app.routers import portfolio_opt as portfolio_opt_router
from app.routers import position_costs as position_costs_router
from app.routers import portfolio_overrides as portfolio_overrides_router
from app.routers import portfolio_snapshots as portfolio_snapshots_router
from app.routers import predictions as predictions_router
from app.routers import quantlib as quantlib_router
from app.routers import reports as reports_router
from app.routers import screener as screener_router
from app.routers import sectors as sectors_router
from app.routers import signals as signals_router
from app.routers import research as research_router
from app.routers import risk as risk_router
from app.routers import scheduler as scheduler_router
from app.routers import settings as settings_router
from app.routers import social as social_router
from app.routers import stream as stream_router
from app.routers import strategy_health as strategy_health_router
from app.routers import strategies as strategies_router
from app.routers import symbols as symbols_router
from app.routers import valuation as valuation_router
from app.routers import workflow as workflow_router
from app.routers import workspace as workspace_router
from app.services import (
    bot_controller,
    polygon_ws_publisher,
    scheduled_jobs,
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
    await app_scheduler.start()
    scheduled_jobs.register_default_jobs()

    # Register any active scheduled workflows. Needs a DB session, so it
    # can't live inside register_default_jobs() — see workflow_service.
    try:
        from app.database import AsyncSessionLocal
        from app.services import workflow_service
        async with AsyncSessionLocal() as session:
            await workflow_service.register_workflow_jobs(session)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "register_workflow_jobs failed at startup"
        )

    await polygon_ws_publisher.start()

    # Re-register user-uploaded strategies after DB is up.
    try:
        from app.database import AsyncSessionLocal
        from app.services import code_service
        async with AsyncSessionLocal() as session:
            await code_service.reload_all_user_strategies(session)
    except Exception:
        # Never let user-strategy reload failures block boot.
        import logging
        logging.getLogger(__name__).exception("reload_all_user_strategies failed at startup")

    try:
        yield
    finally:
        await polygon_ws_publisher.shutdown()
        await app_scheduler.shutdown()
        await bot_controller.shutdown_bot()


configure_logging()

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
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(HttpMetricsMiddleware)

if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="assets")


app.include_router(account_router.router)
app.include_router(agents_router.router)
app.include_router(monitoring_router.router)
app.include_router(quantlib_router.router)
app.include_router(research_router.router)
app.include_router(risk_router.router)
app.include_router(strategies_router.router)
app.include_router(alerts_router.router)
app.include_router(backtest_router.router)
app.include_router(social_router.router)
app.include_router(bot_router.router)
app.include_router(code_router.router)
app.include_router(health_router.router)
app.include_router(journal_router.router)
app.include_router(metrics_router.router)
app.include_router(settings_router.router)
app.include_router(strategy_health_router.router)
# Tradewell-inspired additions
app.include_router(arena_router.router)
app.include_router(crypto_router.router)
app.include_router(macro_router.router)
app.include_router(valuation_router.router)
app.include_router(options_chain_router.router)
app.include_router(pine_seeds_router.router)
app.include_router(portfolio_opt_router.router)
app.include_router(portfolio_overrides_router.router)
app.include_router(portfolio_snapshots_router.router)
app.include_router(position_costs_router.router)
app.include_router(predictions_router.router)
app.include_router(reports_router.router)
app.include_router(scheduler_router.router)
app.include_router(screener_router.router)
app.include_router(sectors_router.router)
app.include_router(signals_router.router)
app.include_router(dbnomics_router.router)
app.include_router(docs_router.router)
app.include_router(geopolitics_router.router)
app.include_router(heatmap_router.router)
app.include_router(indicators_router.router)
app.include_router(kraken_router.router)
app.include_router(onchain_router.router)
app.include_router(stream_router.router)
app.include_router(broker_accounts_router.router)
app.include_router(symbols_router.router)
app.include_router(workflow_router.router)
app.include_router(workspace_router.router)


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
