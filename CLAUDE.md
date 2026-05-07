# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Personal Automated Trading Platform — FastAPI backend + React SPA for paper-trading execution, multi-source market monitoring, portfolio analytics, and AI-assisted research. Paper trading only; the strategy runner targets Alpaca paper accounts.

Constraints from `CONTRIBUTING.md` that influence design:
- No automatic live trading changes unless explicitly discussed.
- Broker write actions stay minimal and auditable.
- Preserve the browser-based runtime settings flow — deployers configure API keys from the UI, not by editing server `.env`.
- Prefer small readable modules over new frameworks/abstractions.

## Common commands

Backend (Python 3.11):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # dev server on :8000

# Tests — local uses pytest (pytest.ini, asyncio_mode=auto)
pytest                                  # all tests
pytest tests/test_monitoring_service.py # single file
pytest tests/test_monitoring_service.py::test_name  # single test
pytest -k "portfolio and not slow"      # by keyword
pytest --cov=app --cov-report=term-missing

# CI runs unittest, not pytest — keep tests compatible:
python -m unittest discover -s tests
```

Frontend (two coexist — see Architecture):

```bash
cd frontend            # legacy SPA, served by FastAPI at "/"
npm install
npm run dev            # :5173
npm run build          # writes frontend/dist (consumed by main.py)

cd frontend-v2         # newer "Trading Raven Console"
npm install
npm run dev            # :5174
npm run build
```

Strategy runner / Docker / Desktop:

```bash
python -m strategy.runner          # Strategy B paper loop (from backend/)
docker compose up --build          # full stack on :8000
./Trading\ Raven\ Desktop.command  # macOS native (pywebview)
./launcher/build_desktop_app.sh    # build .app bundle
```

CLI harness (`agent-harness/`):

```bash
cd agent-harness && pip install .
cli-anything-trading-platform monitoring overview --refresh
```

## Architecture

### Two-frontend layout

`frontend/` is the production SPA referenced by `app/main.py` (mounts `/assets` and serves `index.html` for any non-`/api/*` path from `FRONTEND_DIST_DIR`, override via `TRADING_PLATFORM_FRONTEND_DIST`). `frontend-v2/` is a parallel newer console (Tailwind + react-query + react-router + i18next). When changing user-visible behavior, check whether both frontends need updates, or whether v2 is the only target.

### Backend layering (`backend/app/`)

- `main.py` — FastAPI app, CORS, two custom middlewares (`CorrelationIdMiddleware`, `HttpMetricsMiddleware`), `lifespan` startup that runs `init_database()` → `app_scheduler.start()` → `scheduled_jobs.register_default_jobs()` → `polygon_ws_publisher.start()` → reload of user-uploaded strategies. Every router is included here, then a catch-all GET serves the frontend SPA.
- `routers/` — thin HTTP layer per domain (account, monitoring, portfolio_opt, options_chain, heatmap, sectors, screener, social, kraken, ibkr-driven `broker_accounts`, code sandbox, etc.). Routers should stay thin and delegate to services.
- `services/` — domain logic and external integrations. Major external clients live here: `alpaca_service`, `polygon_service`, `polygon_ws_publisher`, `ibkr_client`/`ibkr_service`, `kraken_service`, `tavily_service`, `openai_service`, `glassnode_service`, `coingecko_service`, `dbnomics_service`, `polymarket_service`, `email_service`, `notifications_service`. Subpackages with their own internal structure: `services/monitoring/` (overview, candidates, watchlist, trends, symbols), `services/social_providers/` (provider strategy: `x_provider`, placeholder `xiaohongshu_provider`), `services/social_signal/` (classify/normalize/scoring/persistence/runner pipeline).
- `models/` — Pydantic request/response schemas per domain (one file per router/service pair).
- `db/` — `engine.py` (async SQLAlchemy + aiosqlite) and `tables.py`. `database.py` is a re-export shim — new code should `from app.db import ...`. SQLite location is `DATA_DIR/trading_platform.db`, falling back to `backend/trading_platform.db`.
- `runtime_settings.py` + `secure_storage_service.py` — store deployer-provided API keys in SQLite (or OS keyring); the settings router never returns secret values to the browser, only `env|stored|default` source markers. Anything that needs an API key reads through here, never directly from `os.environ`.
- `scheduler.py` — singleton `AsyncIOScheduler` with `coalesce=True, max_instances=1`. Use `register_job(...)` from services rather than spawning your own loops. `scheduled_jobs.register_default_jobs()` wires up the recurring tasks (5-min IBKR sync, position snapshots, Polygon WS publisher, etc.).
- `streaming.py` + `polygon_ws_publisher.py` + `routers/stream.py` — server-sent events / pub-sub fan-out for live data.
- `core/` — provider-agnostic computation libraries (no FastAPI deps): `backtest`, `portfolio_opt`, `quantlib`, `quantstats`, `risk`, `indicators`, `sector_rotation`, `valuation`, `predictions`, `news_clustering`, `pine_seeds`, `code_loader` (sandbox for user-uploaded Python strategies), `observability` (logging config). Services orchestrate; `core/` contains the pure logic.

### Strategy runner

Two trading-strategy directories coexist and **both are imported**:
- `backend/strategy/` — has `runner.py` (the entry point invoked as `python -m strategy.runner`) plus `strategy_b.py`.
- `backend/strategies/` — also has `strategy_b.py`. Treat them as distinct modules; do not assume one is dead until you have grepped imports.

User-uploaded strategies are sandboxed via `core/code_loader` and re-registered at startup by `code_service.reload_all_user_strategies`.

### Key conventions

- **Async everywhere on the request path.** Routers, services touching the DB, and external HTTP calls are `async`. Pytest is configured `asyncio_mode = auto`, so test functions can be plain `async def`.
- **Settings reads.** Always go through `runtime_settings` so the SQLite-stored deployer keys take precedence over `.env`. Direct `os.environ` reads for API keys break the runtime settings flow.
- **Scheduler usage.** Register through `app.scheduler.register_job` rather than `asyncio.create_task` loops, so `coalesce`/`max_instances` policy applies and shutdown is clean.
- **Frontend serving.** Any non-`api/` path falls through to `frontend/dist/index.html` — backend route prefixes must start with `/api/` to avoid being shadowed by the SPA fallback.
- **Tests.** CI runs `python -m unittest discover -s tests` — async test code must therefore work under both pytest-asyncio and stdlib `unittest` (use `IsolatedAsyncioTestCase` or pytest-style `async def` that pytest collects; the existing tests do both).

## What lives outside `backend/`

- `agent-harness/` — installable CLI (`cli-anything-trading-platform`) that wraps the same services for scripted/agent automation.
- `launcher/` — macOS/Windows desktop bundlers (pywebview + pyinstaller). Output goes to `output/desktop/...`.
- `documents/` — reference material (not code).
- `docs/superpowers/plans/` — in-progress implementation plans (e.g. APScheduler phasing).
- `Dockerfile` + `docker-compose.yml` — single-service container; persistent volume mounts `DATA_DIR=/app/data`.

## Required runtime keys

For a fully functional dashboard: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `POLYGON_API_KEY`, `TAVILY_API_KEY`. Optional: `OPENAI_API_KEY` (AI candidate selection + Chinese digest), `X_BEARER_TOKEN` (social search), `SETTINGS_ADMIN_TOKEN` (gate the runtime settings UI on shared deploys).

For the SEC EDGAR research integration: `SEC_EDGAR_USER_AGENT` (required by the SEC; format `"<name> <email>"`) — set via the in-app runtime settings UI. `SEC_EDGAR_ENABLED` defaults to true.

## Plugins (dev-time, Claude Code)

The `feat/financial-services-integration` branch installs four Claude Code plugins from `anthropics/financial-services` (marketplace alias `claude-for-financial-services`):

- `financial-analysis@claude-for-financial-services` — foundational skills (`comps-analysis`, `dcf-model`, `3-statement-model`, `xlsx-author`, `pptx-author`, `clean-data-xls`, etc.) and `/comps`, `/dcf`, `/3-statement-model`, `/lbo`, `/competitive-analysis` slash commands.
- `equity-research@claude-for-financial-services` — `/earnings`, `/earnings-preview`, `/initiate`, `/model-update`, `/morning-note`, `/catalysts`, `/sector`, `/thesis`, `/screen` and the matching skill bundles.
- `market-researcher@claude-for-financial-services` — sector/theme research agent (industry overview → peer comps → ideas shortlist).
- `earnings-reviewer@claude-for-financial-services` — post-earnings update agent (filings + transcripts → variance + note draft).

These plugins are **dev-time only** — they augment Claude Code while editing this repo, they do **not** run as part of the platform. Many upstream skills assume paid enterprise MCP data feeds (FactSet, Daloopa, CapIQ, Aiera, Morningstar, S&P Global, Moody's). Without those subscriptions the data-bound steps in skills like `comps-analysis` / `model-update` fall back to whatever public sources the LLM can reach; the document-authoring skills (`xlsx-author`, `pptx-author`) work standalone.

Runtime parity with the upstream agents is provided by the platform's own `/api/research/*` endpoints (see `backend/app/routers/research.py`) which consume free sources (SEC EDGAR + the existing polygon/yfinance/tavily stack).

To uninstall:

```bash
claude plugin uninstall financial-analysis@claude-for-financial-services
claude plugin uninstall equity-research@claude-for-financial-services
claude plugin uninstall market-researcher@claude-for-financial-services
claude plugin uninstall earnings-reviewer@claude-for-financial-services
claude plugin marketplace remove claude-for-financial-services
```
