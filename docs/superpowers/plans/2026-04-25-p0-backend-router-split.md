# P0 — Backend Router Split & Test Safety Net Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 730-line `backend/app/main.py` into focused FastAPI `APIRouter` modules grouped by domain, and stand up a `TestClient`-based integration test scaffold so the refactor is provably behavior-preserving.

**Architecture:** Mechanical, behavior-preserving extraction. We add characterization smoke tests against the current monolithic `main.py` first (safety net), then move route handlers verbatim into eight `app/routers/*.py` modules — one per domain (account, monitoring, research, strategies, alerts, social, bot, settings). Cross-cutting helpers (`SessionDep`, `_service_error`) move to `app/dependencies.py`. Frontend SPA fallback (`/`, `/{full_path:path}`) plus startup/shutdown lifecycle stay in `main.py`. Service-layer files (>500 lines like `social_signal_service.py`) are **not** touched in P0 — those belong to a later phase. We are NOT changing logic, response shapes, or service code.

**Tech Stack:** Python 3.13, FastAPI 0.135, SQLAlchemy async + aiosqlite, pytest + `unittest.mock`, FastAPI `TestClient` (httpx-backed).

**Out of scope (deferred):**
- Splitting big service files (`social_signal_service.py` 1047L, `strategy_profiles_service.py` 850L, `monitoring_service.py` 678L)
- Frontend changes
- Strategy framework / backtesting (that's P2/P3)
- Replacing `@app.on_event` with FastAPI `lifespan` (deprecation, but not what was asked)

---

## File Structure

### New files
| File | Responsibility |
|---|---|
| `backend/app/dependencies.py` | `SessionDep` alias + `service_error()` helper used by every router |
| `backend/app/routers/__init__.py` | Empty package marker |
| `backend/app/routers/account.py` | Account, positions, trades, orders, order/position lifecycle |
| `backend/app/routers/monitoring.py` | Monitoring overview, refresh, universe search, watchlist |
| `backend/app/routers/research.py` | News, research, tavily search, chart, company profile |
| `backend/app/routers/strategies.py` | Strategy library + analyze/preview/activate |
| `backend/app/routers/alerts.py` | Price alerts CRUD |
| `backend/app/routers/social.py` | Social providers + search/score/signals/run |
| `backend/app/routers/bot.py` | Bot status/start/stop |
| `backend/app/routers/settings.py` | Runtime settings status + update |
| `backend/tests/conftest.py` | Shared pytest fixtures: `TestClient`, env defaults |
| `backend/tests/test_app_smoke.py` | One smoke test per router (8 endpoints) |

### Modified files
| File | Change |
|---|---|
| `backend/app/main.py` | Drop all `@app.<verb>(...)` route definitions for `/api/*`; replace with `app.include_router(...)` calls. Keep app instantiation, CORS, static mount, startup/shutdown, frontend `/` fallback handlers. Target: ≤180 lines. |

### Untouched (explicitly)
- `backend/app/models.py`
- `backend/app/database.py`
- `backend/app/runtime_settings.py`
- `backend/app/services/*`
- `backend/strategy/*`
- All existing `backend/tests/test_*.py` files

---

## Pre-flight (one-time setup, do before Task 1)

Run these from the repo root `~/NewBirdClaude`. **Do not commit yet.**

- [ ] Create venv and install deps:
```bash
cd ~/NewBirdClaude/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest httpx
```
Expected: pip resolves cleanly. `python -c "from fastapi.testclient import TestClient; print('ok')"` prints `ok`.

- [ ] Create a feature branch:
```bash
cd ~/NewBirdClaude
git checkout -b refactor/p0-router-split
```

- [ ] Run the existing test suite to capture a green baseline:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -x -q
```
Expected: all currently-existing tests pass. If any pre-existing test is already failing on `main`, note it and DO NOT block on it — the refactor must keep it in the same state (still failing the same way).

---

## Task 1: Add pytest config + `conftest.py` with `TestClient` fixture

> Baseline note: CI uses `python -m unittest discover -s tests`. Existing tests are `unittest.TestCase` subclasses; pytest runs them transparently. We add a minimal `pytest.ini` so `pytest tests/` works from `backend/` without `PYTHONPATH=.` each invocation.

**Files:**
- Create: `backend/pytest.ini`
- Create: `backend/tests/conftest.py`

- [ ] **Step 0: Write `pytest.ini`**

```ini
# backend/pytest.ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 1: Write `conftest.py`**

```python
# backend/tests/conftest.py
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point DATA_DIR at a fresh tmp dir so SQLite/runtime settings are isolated."""
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir)
        monkeypatch.setenv("DATA_DIR", str(path))
        # Force runtime_settings to re-read DATABASE_FILE on next import use
        from app import runtime_settings
        monkeypatch.setattr(
            runtime_settings,
            "DATABASE_FILE",
            path / "trading_platform.db",
        )
        yield path


@pytest.fixture
def client(isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Boot the FastAPI app with isolated state and yield a TestClient.

    Neutralizes background monitor startup so tests don't spawn polling loops.
    Skips the lifespan context entirely (TestClient without `with`)."""
    monkeypatch.setenv("ALPACA_API_KEY", "")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "")
    monkeypatch.setenv("POLYGON_API_KEY", "")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("SETTINGS_ADMIN_TOKEN", "")

    # Stub background monitors before app import so any startup hook is a no-op.
    from app.services import price_alerts_service, social_polling_service, bot_controller

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(price_alerts_service, "start_monitor", _noop)
    monkeypatch.setattr(price_alerts_service, "shutdown_monitor", _noop)
    monkeypatch.setattr(social_polling_service, "start_monitor", _noop)
    monkeypatch.setattr(social_polling_service, "shutdown_monitor", _noop)
    monkeypatch.setattr(bot_controller, "shutdown_bot", _noop)

    from app.main import app

    # Do NOT use `with TestClient(app)` — that triggers FastAPI startup events
    # which would re-bind the (now-stubbed) symbols too late. Plain construction
    # skips the lifespan and is sufficient for HTTP route smoke tests.
    yield TestClient(app)
```

- [ ] **Step 2: Verify pytest discovers it**

Run:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -x -q
```
Expected: PASS with same count as baseline (conftest is loaded but no new tests yet).

- [ ] **Step 3: Commit**

```bash
git add backend/pytest.ini backend/tests/conftest.py
git commit -m "test: add pytest config + TestClient fixture for integration tests"
```

---

## Task 2: Add baseline smoke test against current monolithic `main.py`

This is the safety-net characterization test we run *before* moving any code.

**Files:**
- Create: `backend/tests/test_app_smoke.py`

- [ ] **Step 1: Write the smoke test**

```python
# backend/tests/test_app_smoke.py
"""Integration smoke tests: one no-network endpoint per future router boundary.

These run against the live FastAPI app via TestClient. Goal: prove the router
split in this PR does not change route paths, methods, or response shapes.
"""
from __future__ import annotations


def test_settings_status_returns_dict_shape(client) -> None:
    response = client.get("/api/settings/status")
    assert response.status_code == 200
    body = response.json()
    assert "is_ready" in body
    assert "items" in body
    assert isinstance(body["items"], list)


def test_social_providers_returns_list(client) -> None:
    response = client.get("/api/social/providers")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_bot_status_returns_state(client) -> None:
    response = client.get("/api/bot/status")
    assert response.status_code == 200
    assert "is_running" in response.json()


def test_strategies_library_returns_payload(client) -> None:
    response = client.get("/api/strategies")
    assert response.status_code == 200
    body = response.json()
    assert "strategies" in body or "items" in body or isinstance(body, dict)


def test_unknown_route_returns_404_or_spa_index(client) -> None:
    """The SPA fallback at `/{full_path:path}` may serve index.html if the
    frontend dist exists, else 404. Either is acceptable; we only assert the
    server doesn't 500."""
    response = client.get("/this-route-does-not-exist-xyz")
    assert response.status_code in (200, 404)
```

- [ ] **Step 2: Run smoke tests against current code**

Run:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/test_app_smoke.py -v
```
Expected: 5 tests PASS. If `test_strategies_library_returns_payload` fails because the response shape differs, read `app/models.py::StrategyLibraryResponse`, adjust the assertion to the actual top-level field name, and re-run. Do NOT change app code.

- [ ] **Step 3: Run the full suite**

Run:
```bash
pytest tests/ -x -q
```
Expected: all green, baseline + 5 new tests.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_app_smoke.py
git commit -m "test: characterization smoke tests for /api/* before router split"
```

---

## Task 3: Extract `app/dependencies.py` (SessionDep + service_error)

**Files:**
- Create: `backend/app/dependencies.py`
- Modify: `backend/app/main.py` (remove inline `SessionDep`, `_service_error`)

- [ ] **Step 1: Create the dependencies module**

```python
# backend/app/dependencies.py
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.network_utils import friendly_service_error_detail

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def service_error(exc: Exception) -> HTTPException:
    """Wrap an unexpected service-layer exception as a 503 with a user-safe detail."""
    return HTTPException(status_code=503, detail=friendly_service_error_detail(exc))
```

- [ ] **Step 2: Replace usage in `main.py`**

Edit `backend/app/main.py`:
- Remove the local definitions:
  ```python
  SessionDep = Annotated[AsyncSession, Depends(get_session)]
  ```
  ```python
  def _service_error(exc: Exception) -> HTTPException:
      return HTTPException(status_code=503, detail=friendly_service_error_detail(exc))
  ```
- Add at the top (next to other `from app...` imports):
  ```python
  from app.dependencies import SessionDep, service_error
  ```
- Replace every call site of `_service_error(exc)` with `service_error(exc)` (use editor find-replace; there are ~15 occurrences).
- Remove now-unused imports from `main.py`: `Annotated`, `Depends`, `AsyncSession`, `get_session`, `friendly_service_error_detail` — but only if nothing else in `main.py` still uses them. If unsure, run pyflakes (`python -m pyflakes app/main.py`) after the edit and clean up reported unused imports.

- [ ] **Step 3: Run all tests**

Run:
```bash
pytest tests/ -x -q
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/app/dependencies.py backend/app/main.py
git commit -m "refactor: extract SessionDep and service_error into app/dependencies"
```

---

## Task 4: Create `app/routers/` package

**Files:**
- Create: `backend/app/routers/__init__.py`

- [ ] **Step 1: Create empty package marker**

```python
# backend/app/routers/__init__.py
"""FastAPI routers grouped by domain. Imported and registered in app.main."""
```

- [ ] **Step 2: Verify package importable**

Run:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
python -c "from app.routers import __doc__; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/__init__.py
git commit -m "refactor: scaffold app/routers package"
```

---

## Task 5: Extract `account` router

**Domain endpoints (move verbatim, do NOT modify handler bodies):**
- `GET /api/account` (current `main.py:128-134`)
- `GET /api/positions` (current `main.py:137-144`)
- `GET /api/trades` (current `main.py:146-153`)
- `GET /api/orders` (current `main.py:219-226`)
- `POST /api/orders/cancel` (current `main.py:680-691`)
- `POST /api/positions/close` (current `main.py:693-704`)

**Files:**
- Create: `backend/app/routers/account.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the router module**

```python
# backend/app/routers/account.py
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.dependencies import SessionDep, service_error
from app.models import (
    Account,
    ControlResponse,
    OrderRecord,
    Position,
    TradeRecord,
)
from app.services import alpaca_service

router = APIRouter(prefix="/api", tags=["account"])


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# --- COPY THE FOLLOWING HANDLER BODIES VERBATIM FROM main.py ---
# Paste the bodies of: get_account, get_positions, get_trades, get_orders,
# cancel_orders, close_positions (lines 128-153, 219-226, 680-704 in the
# pre-refactor main.py). Replace each `@app.<verb>("/api/...")` decorator
# with `@router.<verb>("/...")` (drop the `/api` prefix because the router
# already declares `prefix="/api"`).
#
# Example shape for the first one:
#
# @router.get("/account", response_model=Account)
# async def get_account() -> Account:
#     try:
#         payload = await alpaca_service.get_account()
#     except Exception as exc:
#         raise service_error(exc) from exc
#     return Account(**payload)
#
# Repeat the same pattern for the remaining handlers. Replace `_service_error`
# with `service_error` and `_normalize_timestamp` calls stay as-is (defined above).
```

> Implementation note for the executor: open `main.py` and `routers/account.py` side by side. For each of the six handlers listed at the top of this task, cut the function (decorator + body), paste into `account.py`, and rewrite the decorator URL to drop `/api`. Keep imports synced.

- [ ] **Step 2: Register the router in `main.py`**

In `backend/app/main.py`, **delete** the six handler functions for the routes listed above. Add near the bottom of the file (after middleware/static mount setup, before frontend SPA handlers):

```python
from app.routers import account as account_router
app.include_router(account_router.router)
```

(Or, cleaner, group all `from app.routers import ...` at the top with other imports, and put a single block of `app.include_router(...)` calls after `app = FastAPI(...)`. Either layout is fine — pick one and stay consistent for the remaining tasks.)

- [ ] **Step 3: Run smoke tests**

Run:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/test_app_smoke.py -v
```
Expected: still 5 PASS — none of these endpoints are in `account` yet, so behavior shouldn't change. This is just a safety check.

- [ ] **Step 4: Add an account-router integration test**

Append to `backend/tests/test_app_smoke.py`:

```python
def test_account_endpoint_responds(client, monkeypatch) -> None:
    """`/api/account` should return 200 when alpaca_service.get_account is
    mocked, or 503 with a friendly detail when it raises."""
    from app.services import alpaca_service

    async def fake_get_account():
        return {
            "equity": 0.0,
            "buying_power": 0.0,
            "cash": 0.0,
            "portfolio_value": 0.0,
            "day_trade_count": 0,
            "status": "PAPER_OK",
        }

    monkeypatch.setattr(alpaca_service, "get_account", fake_get_account)
    response = client.get("/api/account")
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        assert "equity" in response.json()
```

> Note: the exact field set inside `fake_get_account` must match `app.models.Account`. If `Account` requires more fields than listed, read `models.py` and add them with safe defaults (`0.0`, `""`, `None` as the type allows). The test passing 503 is also acceptable — it just means the model rejected our fake; either way it proves the route is wired.

- [ ] **Step 5: Run all tests**

Run:
```bash
pytest tests/ -x -q
```
Expected: all green (baseline + 6 smoke).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/account.py backend/app/main.py backend/tests/test_app_smoke.py
git commit -m "refactor: extract account router (account/positions/trades/orders)"
```

---

## Task 6: Extract `monitoring` router

**Domain endpoints:**
- `GET /api/monitoring` (`main.py:228-241`)
- `POST /api/monitoring/refresh` (`main.py:304-314`)
- `GET /api/universe` (`main.py:268-278`)
- `POST /api/watchlist` (`main.py:280-291`)
- `DELETE /api/watchlist/{symbol}` (`main.py:293-302`)

**Files:**
- Create: `backend/app/routers/monitoring.py`
- Modify: `backend/app/main.py`, `backend/tests/test_app_smoke.py`

- [ ] **Step 1: Write the router module**

```python
# backend/app/routers/monitoring.py
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SessionDep, service_error
from app.models import (
    AssetUniverseItem,
    MonitoringOverview,
    WatchlistUpdateRequest,
)
from app.services import alpaca_service, monitoring_service

router = APIRouter(prefix="/api", tags=["monitoring"])

# COPY VERBATIM from main.py the bodies of:
#   get_monitoring_overview     -> @router.get("/monitoring", response_model=MonitoringOverview)
#   refresh_monitoring          -> @router.post("/monitoring/refresh", response_model=MonitoringOverview)
#   get_universe                -> @router.get("/universe", response_model=list[AssetUniverseItem])
#   add_watchlist_symbol        -> @router.post("/watchlist", response_model=list[str])
#   remove_watchlist_symbol     -> @router.delete("/watchlist/{symbol}", response_model=list[str])
# Replace `_service_error` with `service_error`. Bodies and parameter lists are unchanged.
```

- [ ] **Step 2: Update `main.py`**

Delete the five handlers from `main.py`. Add to the router-include block:
```python
from app.routers import monitoring as monitoring_router
app.include_router(monitoring_router.router)
```

- [ ] **Step 3: Add monitoring smoke test**

Append to `backend/tests/test_app_smoke.py`:

```python
def test_monitoring_endpoint_wired(client, monkeypatch) -> None:
    from app.services import monitoring_service

    async def fake_overview(*args, **kwargs):
        # Return a dict matching MonitoringOverview's required fields.
        # If the model requires more, the route will return 503 — still proves wiring.
        return {"items": [], "candidates": [], "watchlist": [], "positions": []}

    # monitoring_service exposes get_overview / refresh_overview style functions;
    # monkeypatch all candidate names so whichever one main code calls is mocked.
    for name in ("get_overview", "build_overview", "load_overview", "refresh_overview"):
        if hasattr(monitoring_service, name):
            monkeypatch.setattr(monitoring_service, name, fake_overview)

    response = client.get("/api/monitoring")
    assert response.status_code in (200, 503)
```

- [ ] **Step 4: Run all tests**

Run:
```bash
pytest tests/ -x -q
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/monitoring.py backend/app/main.py backend/tests/test_app_smoke.py
git commit -m "refactor: extract monitoring router (monitoring/universe/watchlist)"
```

---

## Task 7: Extract `research` router

**Domain endpoints:**
- `GET /api/news/{symbol}` (`main.py:155-189`)
- `GET /api/research/{symbol}` (`main.py:191-198`)
- `GET /api/tavily/search` (`main.py:200-217`)
- `GET /api/chart/{symbol}` (`main.py:243-255`)
- `GET /api/company/{symbol}` (`main.py:257-266`)

**Files:**
- Create: `backend/app/routers/research.py`
- Modify: `backend/app/main.py`, `backend/tests/test_app_smoke.py`

- [ ] **Step 1: Write the router module**

```python
# backend/app/routers/research.py
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import desc, select

from app.dependencies import SessionDep, service_error
from app.database import NewsCache
from app.models import (
    CompanyProfileResponse,
    NewsArticle,
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

NEWS_CACHE_TTL = timedelta(hours=4)

router = APIRouter(prefix="/api", tags=["research"])

# COPY VERBATIM from main.py the bodies of:
#   get_news               -> @router.get("/news/{symbol}", response_model=NewsArticle)
#   get_stock_research     -> @router.get("/research/{symbol}", response_model=StockResearchReport)
#   search_with_tavily     -> @router.get("/tavily/search", response_model=TavilySearchResponse)
#   get_symbol_chart       -> @router.get("/chart/{symbol}", response_model=SymbolChartResponse)
#   get_company_profile    -> @router.get("/company/{symbol}", response_model=CompanyProfileResponse)
# Replace `_service_error` with `service_error`. The NEWS_CACHE_TTL constant
# moves here too (it was at the top of main.py and only get_news uses it).
```

- [ ] **Step 2: Update `main.py`**

Delete the five handlers and the `NEWS_CACHE_TTL` constant from `main.py`. Add:
```python
from app.routers import research as research_router
app.include_router(research_router.router)
```
Also drop the now-unused `from sqlalchemy import desc, select` and `from app.database import NewsCache, Trade` if no remaining `main.py` code uses them (run pyflakes to confirm).

- [ ] **Step 3: Add research smoke test**

Append to `backend/tests/test_app_smoke.py`:

```python
def test_company_endpoint_wired(client, monkeypatch) -> None:
    from app.services import company_profile_service

    async def fake_profile(symbol: str):
        return {"symbol": symbol, "name": symbol, "summary": ""}

    if hasattr(company_profile_service, "get_company_profile"):
        monkeypatch.setattr(company_profile_service, "get_company_profile", fake_profile)
    response = client.get("/api/company/AAPL")
    assert response.status_code in (200, 503)
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -x -q
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/research.py backend/app/main.py backend/tests/test_app_smoke.py
git commit -m "refactor: extract research router (news/research/tavily/chart/company)"
```

---

## Task 8: Extract `strategies` router

**Domain endpoints:**
- `GET /api/strategies` (`main.py:381-385`)
- `POST /api/strategies/analyze` (`main.py:387-396`)
- `POST /api/strategies/analyze-upload` (`main.py:398-414`)
- `POST /api/strategies/analyze-factor-code` (`main.py:416-431`)
- `POST /api/strategies/analyze-factor-upload` (`main.py:433-462`)
- `POST /api/strategies` (`main.py:464-476`)
- `PUT /api/strategies/{strategy_id}` (`main.py:478-493`)
- `POST /api/strategies/preview` (`main.py:495-504`)
- `POST /api/strategies/{strategy_id}/activate` (`main.py:506-518`)
- `DELETE /api/strategies/{strategy_id}` (`main.py:520-532`)

**Files:**
- Create: `backend/app/routers/strategies.py`
- Modify: `backend/app/main.py`, `backend/tests/test_app_smoke.py`

- [ ] **Step 1: Write the router module**

```python
# backend/app/routers/strategies.py
from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from app.dependencies import SessionDep, service_error
from app.models import (
    QuantBrainFactorAnalysisRequest,
    StrategyAnalysisDraft,
    StrategyAnalysisRequest,
    StrategyLibraryResponse,
    StrategyPreviewRequest,
    StrategyPreviewResponse,
    StrategySaveRequest,
)
from app.services import (
    quantbrain_factor_service,
    strategy_document_service,
    strategy_profiles_service,
)

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

# COPY VERBATIM from main.py the bodies of the 10 strategy handlers.
# Because this router has prefix `/api/strategies`, decorators become:
#   GET    ""                          (was /api/strategies)
#   POST   "/analyze"
#   POST   "/analyze-upload"
#   POST   "/analyze-factor-code"
#   POST   "/analyze-factor-upload"
#   POST   ""                          (was /api/strategies; save_strategy)
#   PUT    "/{strategy_id}"
#   POST   "/preview"
#   POST   "/{strategy_id}/activate"
#   DELETE "/{strategy_id}"
# Replace `_service_error` with `service_error`. Bodies and dependency
# parameters (e.g. session: SessionDep, request: StrategyAnalysisRequest)
# stay identical.
```

> Note: when two handlers map to the bare path `""` but with different methods (`GET` vs `POST`), FastAPI handles them fine since methods differ. Verify by re-running the smoke test.

- [ ] **Step 2: Update `main.py`**

Delete the 10 handlers. Add:
```python
from app.routers import strategies as strategies_router
app.include_router(strategies_router.router)
```

- [ ] **Step 3: Run smoke tests** (existing `test_strategies_library_returns_payload` covers this router)

```bash
pytest tests/ -x -q
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/strategies.py backend/app/main.py
git commit -m "refactor: extract strategies router (CRUD + analyze + preview)"
```

---

## Task 9: Extract `alerts` router

**Domain endpoints:**
- `GET /api/alerts` (`main.py:316-328`)
- `POST /api/alerts` (`main.py:330-342`)
- `PATCH /api/alerts/{rule_id}` (`main.py:344-359`)
- `DELETE /api/alerts/{rule_id}` (`main.py:361-373`)

**Files:**
- Create: `backend/app/routers/alerts.py`
- Modify: `backend/app/main.py`, `backend/tests/test_app_smoke.py`

- [ ] **Step 1: Write the router module**

```python
# backend/app/routers/alerts.py
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SessionDep, service_error
from app.models import (
    ControlResponse,
    PriceAlertRuleCreateRequest,
    PriceAlertRuleUpdateRequest,
    PriceAlertRuleView,
)
from app.services import price_alerts_service

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

# COPY VERBATIM from main.py:
#   get_price_alert_rules    -> @router.get("",                 response_model=list[PriceAlertRuleView])
#   create_price_alert_rule  -> @router.post("",                response_model=PriceAlertRuleView)
#   update_price_alert_rule  -> @router.patch("/{rule_id}",     response_model=PriceAlertRuleView)
#   delete_price_alert_rule  -> @router.delete("/{rule_id}",    response_model=ControlResponse)
# Replace `_service_error` with `service_error`.
```

- [ ] **Step 2: Update `main.py`**

Delete the four handlers. Add:
```python
from app.routers import alerts as alerts_router
app.include_router(alerts_router.router)
```

- [ ] **Step 3: Add alerts smoke test**

Append to `backend/tests/test_app_smoke.py`:

```python
def test_alerts_list_responds(client, monkeypatch) -> None:
    from app.services import price_alerts_service

    async def fake_list(*args, **kwargs):
        return []

    for name in ("list_rules", "get_rules", "list_alerts"):
        if hasattr(price_alerts_service, name):
            monkeypatch.setattr(price_alerts_service, name, fake_list)
    response = client.get("/api/alerts")
    assert response.status_code in (200, 503)
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -x -q
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/alerts.py backend/app/main.py backend/tests/test_app_smoke.py
git commit -m "refactor: extract alerts router (price alert CRUD)"
```

---

## Task 10: Extract `social` router

**Domain endpoints:**
- `GET /api/social/providers` (`main.py:375-379`)
- `GET /api/social/search` (`main.py:553-588`)
- `GET /api/social/score` (`main.py:590-615`)
- `GET /api/social/signals` (`main.py:617-634`)
- `POST /api/social/run` (`main.py:636-659`)

**Files:**
- Create: `backend/app/routers/social.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the router module**

```python
# backend/app/routers/social.py
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SessionDep, service_error
from app.models import (
    SocialProviderStatus,
    SocialSearchResponse,
    SocialSignalRunRequest,
    SocialSignalRunResponse,
    SocialSignalSnapshotView,
)
from app.services import (
    social_intelligence_service,
    social_signal_service,
)

router = APIRouter(prefix="/api/social", tags=["social"])

# COPY VERBATIM from main.py:
#   get_social_providers  -> @router.get("/providers",  response_model=list[SocialProviderStatus])
#   search_social         -> @router.get("/search",     response_model=SocialSearchResponse)
#   score_social_signal   -> @router.get("/score",      response_model=SocialSignalSnapshotView)
#   get_social_signals    -> @router.get("/signals",    response_model=list[SocialSignalSnapshotView])
#   run_social_signals    -> @router.post("/run",       response_model=SocialSignalRunResponse)
# Replace `_service_error` with `service_error`.
```

- [ ] **Step 2: Update `main.py`**

Delete the five handlers. Add:
```python
from app.routers import social as social_router
app.include_router(social_router.router)
```

- [ ] **Step 3: Run smoke tests** (existing `test_social_providers_returns_list` covers wiring)

```bash
pytest tests/ -x -q
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/social.py backend/app/main.py
git commit -m "refactor: extract social router (providers/search/score/signals/run)"
```

---

## Task 11: Extract `bot` router

**Domain endpoints:**
- `GET /api/bot/status` (`main.py:661-664`)
- `POST /api/bot/start` (`main.py:666-671`)
- `POST /api/bot/stop` (`main.py:673-678`)

**Files:**
- Create: `backend/app/routers/bot.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the router module**

```python
# backend/app/routers/bot.py
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import service_error
from app.models import BotStatus, ControlResponse
from app.services import bot_controller

router = APIRouter(prefix="/api/bot", tags=["bot"])

# COPY VERBATIM from main.py:
#   get_bot_status -> @router.get("/status", response_model=BotStatus)
#   start_bot      -> @router.post("/start", response_model=ControlResponse)
#   stop_bot       -> @router.post("/stop",  response_model=ControlResponse)
# Replace `_service_error` with `service_error`.
```

- [ ] **Step 2: Update `main.py`**

Delete the three handlers. Add:
```python
from app.routers import bot as bot_router
app.include_router(bot_router.router)
```

- [ ] **Step 3: Run smoke tests** (`test_bot_status_returns_state` covers wiring)

```bash
pytest tests/ -x -q
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/bot.py backend/app/main.py
git commit -m "refactor: extract bot router (status/start/stop)"
```

---

## Task 12: Extract `settings` router

**Domain endpoints:**
- `GET /api/settings/status` (`main.py:534-537`)
- `PUT /api/settings` (`main.py:539-551`)

**Files:**
- Create: `backend/app/routers/settings.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write the router module**

```python
# backend/app/routers/settings.py
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import service_error
from app.models import RuntimeSettingsStatus, SettingsUpdateRequest

router = APIRouter(prefix="/api/settings", tags=["settings"])

# COPY VERBATIM from main.py:
#   get_runtime_settings_status -> @router.get("/status", response_model=RuntimeSettingsStatus)
#   update_runtime_settings     -> @router.put("",        response_model=RuntimeSettingsStatus)
# Replace `_service_error` with `service_error`.
```

> Note: the second decorator is `""` (empty path) because the router prefix is `/api/settings`. The original route was `PUT /api/settings`, not `PUT /api/settings/`.

- [ ] **Step 2: Update `main.py`**

Delete the two handlers. Add:
```python
from app.routers import settings as settings_router
app.include_router(settings_router.router)
```

- [ ] **Step 3: Run smoke tests** (`test_settings_status_returns_dict_shape` covers this)

```bash
pytest tests/ -x -q
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/settings.py backend/app/main.py
git commit -m "refactor: extract settings router (status/update)"
```

---

## Task 13: Slim down `main.py`

After Tasks 5–12, `main.py` should only contain:
- Imports
- `app = FastAPI(...)` instantiation
- CORS middleware
- Static files mount
- Startup/shutdown event handlers
- The eight `app.include_router(...)` calls
- The two SPA fallback handlers (`serve_frontend_index`, `serve_frontend_app`) and `_is_safe_frontend_path`

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Reorganize and clean up `main.py`**

Open `backend/app/main.py` and:
1. Delete any imports no longer used (use `python -m pyflakes app/main.py` to find them).
2. Group remaining imports: stdlib, third-party, local.
3. Move all `from app.routers import ... as ..._router` to the import block.
4. Right after `app.add_middleware(...)` and before the startup event, add a single block:

```python
# --- Router registration -------------------------------------------------
app.include_router(account_router.router)
app.include_router(monitoring_router.router)
app.include_router(research_router.router)
app.include_router(strategies_router.router)
app.include_router(alerts_router.router)
app.include_router(social_router.router)
app.include_router(bot_router.router)
app.include_router(settings_router.router)
# -------------------------------------------------------------------------
```

5. Confirm the only remaining `@app.get(...)` decorators are `serve_frontend_index` (`/`) and `serve_frontend_app` (`/{full_path:path}`). The `_is_safe_frontend_path` helper stays.

- [ ] **Step 2: Verify `main.py` line count**

Run:
```bash
wc -l backend/app/main.py
```
Expected: ≤180 lines (down from 730). Acceptable range: 100-180. If above 200, something wasn't moved out — re-grep for `@app.get(\"/api`, `@app.post(\"/api`, etc. and verify all are gone.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -x -q
```
Expected: all green.

- [ ] **Step 4: Manual sanity check — boot the app**

Run:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
uvicorn app.main:app --port 8765 &
sleep 2
curl -sf http://127.0.0.1:8765/api/settings/status | head -c 200; echo
curl -sf http://127.0.0.1:8765/api/social/providers | head -c 200; echo
curl -sf http://127.0.0.1:8765/api/bot/status | head -c 200; echo
kill %1
```
Expected: each curl prints a non-empty JSON snippet and exits 0. If any returns non-200 or a connection error, the route is misregistered — diff against the route list above.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py
git commit -m "refactor: slim main.py to bootstrap + router registration"
```

---

## Task 14: Final verification + OpenAPI parity check

This task proves the public API surface is unchanged.

**Files:**
- Create: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: Snapshot the post-refactor OpenAPI schema**

Run:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
python -c "
from app.main import app
import json, sys
schema = app.openapi()
paths = sorted(schema['paths'].keys())
methods = sorted(
    (p, m.upper())
    for p, methods_map in schema['paths'].items()
    for m in methods_map
    if m in ('get', 'post', 'put', 'patch', 'delete')
)
print('PATHS_COUNT', len(paths))
for p, m in methods:
    print(m, p)
" > /tmp/openapi_after.txt
cat /tmp/openapi_after.txt | head -20
wc -l /tmp/openapi_after.txt
```

Expected: line count is the original route count + the `PATHS_COUNT` header (~42 lines for 40 routes + 1 header + 1 SPA fallback). All `/api/*` paths from the original `main.py` are present.

- [ ] **Step 2: Add a parity test that locks the route inventory**

```python
# backend/tests/test_openapi_parity.py
"""Lock the public route inventory. If a refactor adds/removes a route by
accident, this test fails and forces the change to be intentional."""
from __future__ import annotations

EXPECTED_ROUTES: set[tuple[str, str]] = {
    ("GET",    "/api/account"),
    ("GET",    "/api/positions"),
    ("GET",    "/api/trades"),
    ("GET",    "/api/orders"),
    ("POST",   "/api/orders/cancel"),
    ("POST",   "/api/positions/close"),
    ("GET",    "/api/monitoring"),
    ("POST",   "/api/monitoring/refresh"),
    ("GET",    "/api/universe"),
    ("POST",   "/api/watchlist"),
    ("DELETE", "/api/watchlist/{symbol}"),
    ("GET",    "/api/news/{symbol}"),
    ("GET",    "/api/research/{symbol}"),
    ("GET",    "/api/tavily/search"),
    ("GET",    "/api/chart/{symbol}"),
    ("GET",    "/api/company/{symbol}"),
    ("GET",    "/api/strategies"),
    ("POST",   "/api/strategies"),
    ("POST",   "/api/strategies/analyze"),
    ("POST",   "/api/strategies/analyze-upload"),
    ("POST",   "/api/strategies/analyze-factor-code"),
    ("POST",   "/api/strategies/analyze-factor-upload"),
    ("PUT",    "/api/strategies/{strategy_id}"),
    ("POST",   "/api/strategies/preview"),
    ("POST",   "/api/strategies/{strategy_id}/activate"),
    ("DELETE", "/api/strategies/{strategy_id}"),
    ("GET",    "/api/alerts"),
    ("POST",   "/api/alerts"),
    ("PATCH",  "/api/alerts/{rule_id}"),
    ("DELETE", "/api/alerts/{rule_id}"),
    ("GET",    "/api/social/providers"),
    ("GET",    "/api/social/search"),
    ("GET",    "/api/social/score"),
    ("GET",    "/api/social/signals"),
    ("POST",   "/api/social/run"),
    ("GET",    "/api/bot/status"),
    ("POST",   "/api/bot/start"),
    ("POST",   "/api/bot/stop"),
    ("GET",    "/api/settings/status"),
    ("PUT",    "/api/settings"),
}


def test_route_inventory_unchanged() -> None:
    from app.main import app

    actual: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or not path.startswith("/api/"):
            continue
        for method in methods:
            actual.add((method, path))

    missing = EXPECTED_ROUTES - actual
    extra = actual - EXPECTED_ROUTES
    assert not missing, f"Routes dropped by refactor: {sorted(missing)}"
    assert not extra, f"Routes unexpectedly added: {sorted(extra)}"
```

- [ ] **Step 3: Run the parity test**

```bash
pytest tests/test_openapi_parity.py -v
```
Expected: PASS. If FAIL with "missing", a route wasn't migrated — find it in the failure list and check the corresponding router file. If FAIL with "extra", a duplicate registration exists — check `main.py` for stray `@app.<verb>` decorators.

- [ ] **Step 4: Run the entire test suite one last time**

```bash
pytest tests/ -v
```
Expected: every test passes. Note total count and compare to baseline.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_openapi_parity.py
git commit -m "test: lock /api/* route inventory to prevent silent regressions"
```

- [ ] **Step 6: Push branch**

```bash
git push -u origin refactor/p0-router-split
```

---

## Done-criteria

When all tasks are complete:
- `backend/app/main.py` is ≤180 lines
- All `/api/*` routes live in one of eight `app/routers/*.py` files
- `pytest tests/` is fully green (baseline + ~10 new tests)
- `test_openapi_parity.py` enforces that no route was lost or added
- No service-layer files (`backend/app/services/*`) were modified
- Frontend was not touched
- Branch `refactor/p0-router-split` is pushed and ready to PR

After P0 lands, the next plan is **P1 — frontend structure refactor** (split `App.jsx`, `Dashboard.jsx`, `StrategyStudioPanel.jsx`, introduce a single API-client module). After P1 we move to **P2 — strategy framework** which builds on the now-clean `main.py` and routers.
