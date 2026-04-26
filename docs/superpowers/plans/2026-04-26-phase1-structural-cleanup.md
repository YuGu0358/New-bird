# Phase 1 — Backend Structural Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pay down P0's deferred backend structural debt — eliminate the `@app.on_event` deprecation, split the three remaining oversized files (`app/models.py` 501L, `app/database.py` 195L, `app/services/monitoring_service.py` 678L, `app/services/social_signal_service.py` 1047L) into focused submodules with re-export shims, while keeping every existing import path and behavior identical.

**Architecture:** "Split + shim" pattern: each oversized file becomes a Python package whose `__init__.py` (or a sibling shim file) re-exports the same public symbols. Callers keep `from app.models import X` and `from app.database import Trade` working unchanged. Internal classes/functions move into focused submodules grouped by responsibility. Plus one independent task: rewrite startup/shutdown using FastAPI's `lifespan` async-context-manager API.

**Tech Stack:** Python 3.13, FastAPI 0.135, SQLAlchemy async + aiosqlite, pytest. No new dependencies.

**Out of scope (deferred):**
- `strategy_profiles_service.py` (850L) — Phase 2 will redesign it around the new `Strategy` ABC, splitting it now would be wasted work.
- `agent-harness/` HTTP decoupling — separate Phase 1.5 plan.
- Any service logic changes / bug fixes / new features.
- Frontend (frozen by user).
- Alembic migrations (Phase 2).

---

## File Structure

### New packages
| Package | Replaces | Modules |
|---|---|---|
| `backend/app/models/` | `app/models.py` (deleted at end; shim NOT needed since `app.models` resolves to package `__init__.py`) | `account.py` `research.py` `monitoring.py` `alerts.py` `social.py` `settings.py` `strategies.py` `__init__.py` (re-exports) |
| `backend/app/db/` | `app/database.py` (kept as one-line shim re-exporting from `app.db`) | `engine.py` `tables.py` `__init__.py` (re-exports) |
| `backend/app/services/monitoring/` | `app/services/monitoring_service.py` (kept as shim) | `symbols.py` `watchlist.py` `trends.py` `candidates.py` `overview.py` `__init__.py` (re-exports) |
| `backend/app/services/social_signal/` | `app/services/social_signal_service.py` (kept as shim) | `models.py` `normalize.py` `classify.py` `scoring.py` `persistence.py` `runner.py` `__init__.py` (re-exports) |

### Modified files
| File | Change |
|---|---|
| `backend/app/main.py` | Replace `@app.on_event(...)` handlers with a `lifespan` async-context-manager passed to `FastAPI(...)`. |
| `backend/app/services/monitoring_service.py` | Becomes a 1–3 line shim: `from app.services.monitoring import *  # noqa: F401, F403` plus an `__all__` if needed. |
| `backend/app/services/social_signal_service.py` | Same shim pattern. |
| `backend/app/database.py` | Same shim pattern: `from app.db import *  # noqa: F401, F403`. |

### Deleted files
| File | Reason |
|---|---|
| `backend/app/models.py` | Replaced by `app/models/` package — Python resolves `app.models` to the package automatically, no shim needed. |

### Untouched
- All `backend/app/routers/*.py`
- All other files under `backend/app/services/*` (only the two big ones move)
- `backend/strategy/*`
- `backend/tests/*` — existing tests must pass without modification
- `frontend/*`
- `agent-harness/*`
- `launcher/*`, `Dockerfile`, `docker-compose.yml`, CI workflows

---

## Pre-flight

Run these from `~/NewBirdClaude`. Already done from P0:
- `backend/.venv` exists with deps + pytest
- `git checkout refactor/p0-router-split` is the active branch

- [ ] Confirm baseline:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **60 passed**.

- [ ] Create Phase 1 branch off P0:
```bash
cd ~/NewBirdClaude
git checkout -b refactor/p1-structural-cleanup
```

> Reasoning: P0 PR may not be merged yet. Stacking Phase 1 on top of P0 keeps the work going; if P0 merges first, rebase Phase 1 onto `main` cleanly (no overlap — P1 only touches files P0 didn't modify, except `main.py` which has no router-related conflict).

---

## Task 1: Migrate `@app.on_event` → `lifespan`

**Files:**
- Modify: `backend/app/main.py`

**Why:** FastAPI deprecated `on_event` in favor of `lifespan` async context managers. Currently `pytest` emits 4 DeprecationWarnings; this task eliminates them and gives us a single testable startup/shutdown function.

- [ ] **Step 1: Edit `main.py`**

In `backend/app/main.py`:

1. At the top of the file, add the import:
```python
from contextlib import asynccontextmanager
```

2. Above the `app = FastAPI(...)` line, define:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown sequence.

    Replaces the deprecated @app.on_event handlers. Tests bypass this by
    constructing TestClient(app) without the `with` context manager.
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
```

3. Pass `lifespan=lifespan` to the FastAPI constructor:
```python
app = FastAPI(
    title="Personal Automated Trading Platform",
    version="1.0.0",
    lifespan=lifespan,
)
```

4. Delete the two `@app.on_event(...)` functions (`startup_event`, `shutdown_event`).

- [ ] **Step 2: Run tests**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **60 passed, 0 deprecation warnings about `on_event`** (other warnings may remain). If `60 passed` but the `on_event` warning is still present, you missed deleting one of the two handlers.

- [ ] **Step 3: Sanity boot**

```bash
(uvicorn app.main:app --port 8765 > /tmp/uv.log 2>&1 &); sleep 3
curl -s -o /dev/null -w "settings: %{http_code}\n" http://127.0.0.1:8765/api/settings/status
pkill -f "uvicorn app.main:app --port 8765"; sleep 1
grep -E "Application startup complete|Started server|ERROR" /tmp/uv.log | head
```
Expected: `settings: 200`, log shows `Application startup complete`, no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "refactor: migrate @app.on_event handlers to lifespan context manager"
```

---

## Task 2: Split `app/models.py` into `app/models/` package

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/account.py`
- Create: `backend/app/models/research.py`
- Create: `backend/app/models/monitoring.py`
- Create: `backend/app/models/alerts.py`
- Create: `backend/app/models/social.py`
- Create: `backend/app/models/settings.py`
- Create: `backend/app/models/strategies.py`
- Delete: `backend/app/models.py`

**Mapping (model class → submodule):**

| Submodule | Classes |
|---|---|
| `account.py` | `Account`, `Position`, `TradeRecord`, `OrderRecord`, `BotStatus`, `ControlResponse` |
| `research.py` | `NewsArticle`, `ResearchSource`, `StockResearchReport`, `TavilySearchSource`, `TavilySearchResponse`, `ChartPoint`, `SymbolChartResponse`, `CompanyProfileResponse` |
| `monitoring.py` | `AssetUniverseItem`, `TrendSnapshot`, `CandidatePoolEntry`, `TrackedSymbolView`, `MonitoringOverview`, `WatchlistUpdateRequest` |
| `alerts.py` | `PriceAlertRuleCreateRequest`, `PriceAlertRuleUpdateRequest`, `PriceAlertRuleView` |
| `social.py` | `SocialProviderStatus`, `SocialPostAuthor`, `SocialPostMetrics`, `SocialCountBucket`, `SocialPostItem`, `SocialSearchResponse`, `SocialSignalQueryProfile`, `SocialSignalSource`, `SocialSignalSnapshotView`, `SocialSignalRunRequest`, `SocialSignalRunResponse` |
| `settings.py` | `RuntimeSettingItem`, `RuntimeSettingsStatus`, `SettingsUpdateRequest` |
| `strategies.py` | `StrategyExecutionParameters`, `StrategyAnalysisRequest`, `QuantBrainFactorAnalysis`, `QuantBrainFactorAnalysisRequest`, `StrategyAnalysisDraft`, `StrategySaveRequest`, `StrategyPreviewRequest`, `StrategyPreviewCandidate`, `StrategyPreviewResponse`, `StoredStrategy`, `StrategyLibraryResponse` |

**Reference:** original line ranges in `backend/app/models.py` (read the file before splitting):
- `Account` ≈ 9, `Position` ≈ 19, `TradeRecord` ≈ 28, `NewsArticle` ≈ 42, `OrderRecord` ≈ 51, `BotStatus` ≈ 63, `ControlResponse` ≈ 71, `ResearchSource` ≈ 76, `StockResearchReport` ≈ 85, `AssetUniverseItem` ≈ 101, `TrendSnapshot` ≈ 112, `CandidatePoolEntry` ≈ 127, `TrackedSymbolView` ≈ 136, `MonitoringOverview` ≈ 142, `ChartPoint` ≈ 150, `SymbolChartResponse` ≈ 159, `CompanyProfileResponse` ≈ 169, `TavilySearchSource` ≈ 187, `TavilySearchResponse` ≈ 197, `WatchlistUpdateRequest` ≈ 205, `PriceAlertRuleCreateRequest` ≈ 209, `PriceAlertRuleUpdateRequest` ≈ 218, `PriceAlertRuleView` ≈ 222, `SocialProviderStatus` ≈ 244, `SocialPostAuthor` ≈ 251, `SocialPostMetrics` ≈ 259, `SocialCountBucket` ≈ 266, `SocialPostItem` ≈ 272, `SocialSearchResponse` ≈ 285, `SocialSignalQueryProfile` ≈ 306, `SocialSignalSource` ≈ 317, `SocialSignalSnapshotView` ≈ 327, `SocialSignalRunRequest` ≈ 345, `SocialSignalRunResponse` ≈ 357, `RuntimeSettingItem` ≈ 363, `RuntimeSettingsStatus` ≈ 375, `SettingsUpdateRequest` ≈ 383, `StrategyExecutionParameters` ≈ 388, `StrategyAnalysisRequest` ≈ 403, `QuantBrainFactorAnalysis` ≈ 407, `QuantBrainFactorAnalysisRequest` ≈ 422, `StrategyAnalysisDraft` ≈ 428, `StrategySaveRequest` ≈ 441, `StrategyPreviewRequest` ≈ 452, `StrategyPreviewCandidate` ≈ 457, `StrategyPreviewResponse` ≈ 466, `StoredStrategy` ≈ 484, `StrategyLibraryResponse` ≈ 498.

- [ ] **Step 1: Read `backend/app/models.py` in full**

Open it. Identify which constants (e.g. enum-like literal lists, helper validators) live alongside class definitions. They move with their primary class.

- [ ] **Step 2: Create each submodule**

For each submodule listed above, create `backend/app/models/<name>.py`. Each file:
1. Starts with `from __future__ import annotations`
2. Imports `from pydantic import BaseModel, Field` (and any extras the moved classes use — check the original imports near the top of `models.py`)
3. Imports any **other** model classes it references via Pydantic forward refs from the proper submodule (e.g. if `MonitoringOverview` references `Position` and `CandidatePoolEntry`, import `Position` from `app.models.account` and use the local `CandidatePoolEntry`).
4. Contains the full class bodies, copy-pasted verbatim.

Cross-module references: walk every `BaseModel` you move and check its field annotations for any other moved class. If found, add an `from app.models.<other_submodule> import <ClassName>` at the top.

- [ ] **Step 3: Write `backend/app/models/__init__.py`**

```python
"""Pydantic API models, grouped by domain.

The flat re-exports preserve the legacy import path:
    from app.models import Account, MonitoringOverview, ...

Internally, callers may also import from the submodule directly:
    from app.models.account import Account
"""
from __future__ import annotations

from app.models.account import (
    Account,
    BotStatus,
    ControlResponse,
    OrderRecord,
    Position,
    TradeRecord,
)
from app.models.alerts import (
    PriceAlertRuleCreateRequest,
    PriceAlertRuleUpdateRequest,
    PriceAlertRuleView,
)
from app.models.monitoring import (
    AssetUniverseItem,
    CandidatePoolEntry,
    MonitoringOverview,
    TrackedSymbolView,
    TrendSnapshot,
    WatchlistUpdateRequest,
)
from app.models.research import (
    ChartPoint,
    CompanyProfileResponse,
    NewsArticle,
    ResearchSource,
    StockResearchReport,
    SymbolChartResponse,
    TavilySearchResponse,
    TavilySearchSource,
)
from app.models.settings import (
    RuntimeSettingItem,
    RuntimeSettingsStatus,
    SettingsUpdateRequest,
)
from app.models.social import (
    SocialCountBucket,
    SocialPostAuthor,
    SocialPostItem,
    SocialPostMetrics,
    SocialProviderStatus,
    SocialSearchResponse,
    SocialSignalQueryProfile,
    SocialSignalRunRequest,
    SocialSignalRunResponse,
    SocialSignalSnapshotView,
    SocialSignalSource,
)
from app.models.strategies import (
    QuantBrainFactorAnalysis,
    QuantBrainFactorAnalysisRequest,
    StoredStrategy,
    StrategyAnalysisDraft,
    StrategyAnalysisRequest,
    StrategyExecutionParameters,
    StrategyLibraryResponse,
    StrategyPreviewCandidate,
    StrategyPreviewRequest,
    StrategyPreviewResponse,
    StrategySaveRequest,
)

__all__ = [
    "Account",
    "AssetUniverseItem",
    "BotStatus",
    "CandidatePoolEntry",
    "ChartPoint",
    "CompanyProfileResponse",
    "ControlResponse",
    "MonitoringOverview",
    "NewsArticle",
    "OrderRecord",
    "Position",
    "PriceAlertRuleCreateRequest",
    "PriceAlertRuleUpdateRequest",
    "PriceAlertRuleView",
    "QuantBrainFactorAnalysis",
    "QuantBrainFactorAnalysisRequest",
    "ResearchSource",
    "RuntimeSettingItem",
    "RuntimeSettingsStatus",
    "SettingsUpdateRequest",
    "SocialCountBucket",
    "SocialPostAuthor",
    "SocialPostItem",
    "SocialPostMetrics",
    "SocialProviderStatus",
    "SocialSearchResponse",
    "SocialSignalQueryProfile",
    "SocialSignalRunRequest",
    "SocialSignalRunResponse",
    "SocialSignalSnapshotView",
    "SocialSignalSource",
    "StockResearchReport",
    "StoredStrategy",
    "StrategyAnalysisDraft",
    "StrategyAnalysisRequest",
    "StrategyExecutionParameters",
    "StrategyLibraryResponse",
    "StrategyPreviewCandidate",
    "StrategyPreviewRequest",
    "StrategyPreviewResponse",
    "StrategySaveRequest",
    "SymbolChartResponse",
    "TavilySearchResponse",
    "TavilySearchSource",
    "TradeRecord",
    "TrackedSymbolView",
    "TrendSnapshot",
    "WatchlistUpdateRequest",
]
```

- [ ] **Step 4: Delete the old file**

```bash
git rm backend/app/models.py
```

> Why deletion (not shim): Python resolves `app.models` to the package `app/models/__init__.py` automatically. Keeping `app/models.py` AND `app/models/` would be ambiguous and is forbidden by Python's import system anyway.

- [ ] **Step 5: Run tests**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **60 passed**.

If a test errors with `ImportError: cannot import name 'X' from 'app.models'`, you missed re-exporting `X` in `__init__.py`. Add it.

If a test errors inside a model with `NameError`, you have a forward reference between two models that landed in different submodules. Add the missing cross-submodule import.

- [ ] **Step 6: Verify the package exposes the same surface**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
python -c "
import app.models as m
expected = {'Account','Position','TradeRecord','NewsArticle','OrderRecord','BotStatus','ControlResponse','ResearchSource','StockResearchReport','AssetUniverseItem','TrendSnapshot','CandidatePoolEntry','TrackedSymbolView','MonitoringOverview','ChartPoint','SymbolChartResponse','CompanyProfileResponse','TavilySearchSource','TavilySearchResponse','WatchlistUpdateRequest','PriceAlertRuleCreateRequest','PriceAlertRuleUpdateRequest','PriceAlertRuleView','SocialProviderStatus','SocialPostAuthor','SocialPostMetrics','SocialCountBucket','SocialPostItem','SocialSearchResponse','SocialSignalQueryProfile','SocialSignalSource','SocialSignalSnapshotView','SocialSignalRunRequest','SocialSignalRunResponse','RuntimeSettingItem','RuntimeSettingsStatus','SettingsUpdateRequest','StrategyExecutionParameters','StrategyAnalysisRequest','QuantBrainFactorAnalysis','QuantBrainFactorAnalysisRequest','StrategyAnalysisDraft','StrategySaveRequest','StrategyPreviewRequest','StrategyPreviewCandidate','StrategyPreviewResponse','StoredStrategy','StrategyLibraryResponse'}
missing = expected - set(dir(m))
print('MISSING:', sorted(missing) if missing else 'none')
print('TOTAL:', len([n for n in dir(m) if not n.startswith('_')]))
"
```
Expected: `MISSING: none` and `TOTAL` ≥ 47.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/
git rm backend/app/models.py
git commit -m "refactor: split app/models.py into domain submodules with re-exports"
```

---

## Task 3: Split `app/database.py` into `app/db/` package

**Files:**
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/engine.py`
- Create: `backend/app/db/tables.py`
- Modify: `backend/app/database.py` (becomes a shim)

**Mapping:**

| Module | Contents (from current `database.py`) |
|---|---|
| `engine.py` | `DATA_DIR`, `DATABASE_FILE`, `DATABASE_URL`, `Base`, `engine`, `AsyncSessionLocal`, `get_session`, `init_database`, plus the SQLAlchemy/aiosqlite imports they need |
| `tables.py` | `Trade`, `NewsCache`, `WatchlistSymbol`, `PriceAlertRule`, `CandidatePoolItem`, `SocialSearchCache`, `StrategyProfile`, `SocialSignalSnapshot` |
| `__init__.py` | Re-exports everything for `from app.db import X` ergonomics |

**Reference line ranges in `backend/app/database.py`:**
- `DATA_DIR` ~15, `DATABASE_FILE` ~17, `DATABASE_URL` ~21, `Base` ~27, `Trade` ~31, `NewsCache` ~49, `WatchlistSymbol` ~63, `PriceAlertRule` ~75, `CandidatePoolItem` ~104, `SocialSearchCache` ~121, `StrategyProfile` ~136, `SocialSignalSnapshot` ~161, `get_session` ~188, `init_database` ~193.

> Cross-module dependency: `tables.py` imports `Base` from `engine.py`. `init_database` in `engine.py` calls `Base.metadata.create_all(...)`, so it must import `tables` (or use a delayed `import app.db.tables` inside the function) to make sure all table classes are registered before `create_all`.

- [ ] **Step 1: Read `backend/app/database.py` in full**

Note every import at the top, every constant, the `Base` declarative base, all eight ORM classes, and the two helper async functions.

- [ ] **Step 2: Create `backend/app/db/engine.py`**

```python
"""SQLAlchemy async engine, session factory, and base classes.

Importing this module also registers all ORM tables (via ``app.db.tables``)
so callers of ``init_database()`` get a complete schema.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

DATA_DIR = os.getenv("DATA_DIR", "").strip()
if DATA_DIR:
    DATABASE_FILE = Path(DATA_DIR) / "trading_platform.db"
else:
    DATABASE_FILE = Path(__file__).resolve().parents[2] / "trading_platform.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATABASE_FILE}")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(AsyncAttrs, DeclarativeBase):
    """SQLAlchemy declarative base for all ORM tables."""


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_database() -> None:
    # Import tables to ensure their classes are registered with Base.metadata
    # before the create_all call. Local import avoids a circular import at
    # module load time (tables.py imports Base from this module).
    from app.db import tables  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

> Verify against the original: if `DATABASE_FILE` was computed differently in the original (e.g. different fallback path), keep the original logic exactly. Read `database.py` lines 15-25 and copy the file-path resolution verbatim.

- [ ] **Step 3: Create `backend/app/db/tables.py`**

```python
"""ORM table definitions. Imported for side effects via app.db.engine.init_database()."""
from __future__ import annotations

# Copy the full set of imports from the top of the original database.py that
# are referenced by ANY of the table classes (datetime, Optional, JSON, Mapped,
# mapped_column, relationship, Integer, String, Float, Boolean, DateTime, Text,
# UniqueConstraint, ForeignKey, etc.). Do NOT duplicate engine/session imports.

from app.db.engine import Base

# Paste the eight ORM classes verbatim from the original database.py (Trade,
# NewsCache, WatchlistSymbol, PriceAlertRule, CandidatePoolItem,
# SocialSearchCache, StrategyProfile, SocialSignalSnapshot). Bodies unchanged.
```

> Replace the comments above with the actual imports + class bodies copied verbatim from `backend/app/database.py`. Do not modify column definitions, constraints, or relationships.

- [ ] **Step 4: Create `backend/app/db/__init__.py`**

```python
"""Database layer: engine + ORM tables.

Re-exports everything callers used to import from app.database, so:
    from app.db import Trade, get_session, init_database, Base
all work.
"""
from __future__ import annotations

from app.db.engine import (
    AsyncSessionLocal,
    Base,
    DATA_DIR,
    DATABASE_FILE,
    DATABASE_URL,
    engine,
    get_session,
    init_database,
)
from app.db.tables import (
    CandidatePoolItem,
    NewsCache,
    PriceAlertRule,
    SocialSearchCache,
    SocialSignalSnapshot,
    StrategyProfile,
    Trade,
    WatchlistSymbol,
)

__all__ = [
    "AsyncSessionLocal",
    "Base",
    "CandidatePoolItem",
    "DATA_DIR",
    "DATABASE_FILE",
    "DATABASE_URL",
    "NewsCache",
    "PriceAlertRule",
    "SocialSearchCache",
    "SocialSignalSnapshot",
    "StrategyProfile",
    "Trade",
    "WatchlistSymbol",
    "engine",
    "get_session",
    "init_database",
]
```

- [ ] **Step 5: Replace `backend/app/database.py` with a shim**

```python
"""Backward-compat shim. New code should import from app.db directly."""
from app.db import *  # noqa: F401, F403
from app.db import __all__  # noqa: F401
```

- [ ] **Step 6: Run tests**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **60 passed**.

Common failure modes:
- `ImportError: cannot import name 'X' from 'app.database'` → missing in `app.db.__init__.py` re-exports.
- `sqlalchemy.exc.InvalidRequestError: Table '...' is already defined` → you accidentally have both the old and new ORM classes loaded simultaneously. Make sure `database.py` is now ONLY the shim, no duplicate class definitions.
- `RuntimeError: There is no current event loop` during `init_database` → unlikely, but if it appears, the issue is that `from app.db import tables` is at module top of `engine.py`, which triggers SQLAlchemy registration before `Base` exists. The local import inside `init_database` (Step 2) avoids this.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/ backend/app/database.py
git commit -m "refactor: split app/database.py into app/db package (engine + tables)"
```

---

## Task 4: Split `app/services/monitoring_service.py` into `monitoring/` package

**Files:**
- Create: `backend/app/services/monitoring/__init__.py`
- Create: `backend/app/services/monitoring/symbols.py`
- Create: `backend/app/services/monitoring/watchlist.py`
- Create: `backend/app/services/monitoring/trends.py`
- Create: `backend/app/services/monitoring/candidates.py`
- Create: `backend/app/services/monitoring/overview.py`
- Modify: `backend/app/services/monitoring_service.py` (becomes a shim)

**Mapping (function → submodule):**

| Submodule | Functions / responsibility |
|---|---|
| `symbols.py` | `_normalize_symbol`, `_normalize_symbols` (shared helpers used by every other submodule) |
| `watchlist.py` | `ensure_default_watchlist`, `get_selected_symbols`, `add_watchlist_symbol`, `remove_watchlist_symbol`, `get_alpaca_universe`, `search_alpaca_universe` |
| `trends.py` | `_empty_trend_snapshot`, `_direction`, `_percent_change`, `_select_reference_price`, `_build_trend_snapshot`, `_history_frame_to_points`, `_download_histories_sync`, `fetch_trend_snapshots` |
| `candidates.py` | `_score_candidate`, `_fallback_candidate_reason`, `_compress_reason`, `_build_candidate_reasons`, `_pick_top_candidates`, `_load_cached_candidate_pool`, `build_candidate_pool` |
| `overview.py` | `get_monitoring_overview` (top-level orchestrator that pulls from the other four) |

**Public API (must be re-exported by `__init__.py`):**
- `get_monitoring_overview`
- `add_watchlist_symbol`
- `remove_watchlist_symbol`
- `get_alpaca_universe`
- `search_alpaca_universe`
- `ensure_default_watchlist`
- `get_selected_symbols`
- `fetch_trend_snapshots`
- `build_candidate_pool`

(Anything starting with `_` stays internal to its submodule, not re-exported.)

- [ ] **Step 1: Read `backend/app/services/monitoring_service.py` in full** (678 lines)

Inventory:
1. Top-of-file imports — note each.
2. Module-level constants (e.g. ETF lists, default universes, score thresholds) — these typically belong with the function that uses them. If a constant is shared by multiple submodules, put it in `symbols.py` (the leaf shared module).
3. Each function's dependencies (which other functions and which constants it calls).

- [ ] **Step 2: Create `symbols.py`**

```python
"""Shared symbol normalization helpers used across monitoring submodules."""
from __future__ import annotations

from collections.abc import Iterable

# Paste the bodies of _normalize_symbol and _normalize_symbols verbatim from
# the original monitoring_service.py.
```

- [ ] **Step 3: Create `watchlist.py`**

```python
"""Watchlist + Alpaca universe queries.

Public:
    ensure_default_watchlist, get_selected_symbols,
    add_watchlist_symbol, remove_watchlist_symbol,
    get_alpaca_universe, search_alpaca_universe
"""
from __future__ import annotations

# Copy imports the moved functions need (sqlalchemy, app.db tables, alpaca_service, etc.)
from app.services.monitoring.symbols import _normalize_symbol, _normalize_symbols

# Paste verbatim: ensure_default_watchlist, get_selected_symbols,
# add_watchlist_symbol, remove_watchlist_symbol, get_alpaca_universe,
# search_alpaca_universe.
```

- [ ] **Step 4: Create `trends.py`**

```python
"""Day/Week/Month trend snapshot computation."""
from __future__ import annotations

# Imports the moved functions need (datetime, yfinance, asyncio, etc.)
from app.services.monitoring.symbols import _normalize_symbol, _normalize_symbols

# Paste verbatim: _empty_trend_snapshot, _direction, _percent_change,
# _select_reference_price, _build_trend_snapshot, _history_frame_to_points,
# _download_histories_sync, fetch_trend_snapshots.
```

- [ ] **Step 5: Create `candidates.py`**

```python
"""AI candidate-pool scoring + selection."""
from __future__ import annotations

# Imports the moved functions need.
from app.services.monitoring.symbols import _normalize_symbol, _normalize_symbols
from app.services.monitoring.trends import fetch_trend_snapshots  # if needed

# Paste verbatim: _score_candidate, _fallback_candidate_reason, _compress_reason,
# _build_candidate_reasons, _pick_top_candidates, _load_cached_candidate_pool,
# build_candidate_pool.
```

> If `build_candidate_pool` imports `openai_service` (likely yes, for AI final selection), include `from app.services import openai_service`.

- [ ] **Step 6: Create `overview.py`**

```python
"""Top-level monitoring overview that combines watchlist + trends + candidates."""
from __future__ import annotations

# Imports.
from app.services.monitoring.watchlist import (
    get_alpaca_universe,
    get_selected_symbols,
)
from app.services.monitoring.trends import fetch_trend_snapshots
from app.services.monitoring.candidates import build_candidate_pool

# Paste verbatim: get_monitoring_overview.
```

- [ ] **Step 7: Create `__init__.py`**

```python
"""Monitoring service package: watchlist, trends, candidate pool, overview."""
from __future__ import annotations

from app.services.monitoring.candidates import build_candidate_pool
from app.services.monitoring.overview import get_monitoring_overview
from app.services.monitoring.trends import fetch_trend_snapshots
from app.services.monitoring.watchlist import (
    add_watchlist_symbol,
    ensure_default_watchlist,
    get_alpaca_universe,
    get_selected_symbols,
    remove_watchlist_symbol,
    search_alpaca_universe,
)

__all__ = [
    "add_watchlist_symbol",
    "build_candidate_pool",
    "ensure_default_watchlist",
    "fetch_trend_snapshots",
    "get_alpaca_universe",
    "get_monitoring_overview",
    "get_selected_symbols",
    "remove_watchlist_symbol",
    "search_alpaca_universe",
]
```

- [ ] **Step 8: Replace `monitoring_service.py` with a shim**

```python
"""Backward-compat shim. New code should import from app.services.monitoring directly."""
from app.services.monitoring import *  # noqa: F401, F403
from app.services.monitoring import __all__  # noqa: F401
```

- [ ] **Step 9: Run tests**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **60 passed**.

If `tests/test_monitoring_service.py` imports private helpers (e.g. `from app.services.monitoring_service import _build_trend_snapshot`), those imports may fail because `*` does not re-export underscore-prefixed names. Fix by either:
- Adding the private helpers explicitly to the shim's re-export, OR
- Updating the test to import from the new submodule path (preferred — follow what's already there).

Before changing tests, run `grep -nE "from app.services.monitoring_service import _" backend/tests/` to find any such imports.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/monitoring/ backend/app/services/monitoring_service.py
git commit -m "refactor: split monitoring_service.py into monitoring/ package"
```

---

## Task 5: Split `app/services/social_signal_service.py` into `social_signal/` package

**Files:**
- Create: `backend/app/services/social_signal/__init__.py`
- Create: `backend/app/services/social_signal/local_models.py`
- Create: `backend/app/services/social_signal/normalize.py`
- Create: `backend/app/services/social_signal/classify.py`
- Create: `backend/app/services/social_signal/scoring.py`
- Create: `backend/app/services/social_signal/persistence.py`
- Create: `backend/app/services/social_signal/runner.py`
- Modify: `backend/app/services/social_signal_service.py` (becomes a shim)

> Naming note: `local_models.py` (not `models.py`) to avoid shadowing `app.models` at the package level via accidental shorthand imports.

**Mapping (function → submodule):**

| Submodule | Functions / classes |
|---|---|
| `local_models.py` | `SocialSignalQueryProfile`, `SocialTextClassification`, `_OpenAIClassificationResponse` (the local Pydantic models defined inside this service file — distinct from the API-level models in `app/models/social.py`) |
| `normalize.py` | `_normalize_symbol`, `_normalize_keywords`, `_parse_timestamp`, `_json_default`, `_clip`, `_format_source`, `_source_failure_reason`, `_build_company_aliases` |
| `classify.py` | `_count_phrase_hits`, `_local_classify_text`, `_openai_classify_text_sync`, `_classify_text`, `_classify_posts`, `_classify_sources` |
| `scoring.py` | `_engagement_weight`, `_author_weight`, `_recency_weight`, `_sentiment_sign`, `_classify_confidence_label`, `_compute_market_score`, `_map_action`, `_downgrade_action`, `_serialize_snapshot`, `_aggregate_social_score`, `_compute_news_adjustment`, `is_market_session_open` |
| `persistence.py` | `_load_positions_map`, `_load_signal_context_symbols`, `_count_today_executions`, `_latest_executed_snapshot_for_symbol`, `_ensure_social_auto_trade_allowed`, `_execute_signal_if_allowed`, `build_query_profile` (uses DB to load context) |
| `runner.py` | `score_symbol_signal`, `get_latest_signals`, `run_social_monitor` (the public API of the module) |

**Public API (re-exported):**
- `score_symbol_signal`
- `get_latest_signals`
- `run_social_monitor`
- `is_market_session_open`
- `build_query_profile`
- Any class names that other code imports (check `grep -rn "from app.services.social_signal_service import" backend/` before splitting).

- [ ] **Step 1: Discover external callers**

```bash
cd ~/NewBirdClaude
grep -rn "from app.services.social_signal_service import\|from app.services import social_signal_service\|social_signal_service\\." backend/ --include="*.py" | grep -v "social_signal_service.py:" | sort -u
```
Note every imported name. The shim must re-export all of them.

- [ ] **Step 2: Read `social_signal_service.py` in full** (1047 lines)

Identify cross-function dependencies. Build a map of: each function → which other functions in this file it calls. This determines submodule import structure.

- [ ] **Step 3: Create `local_models.py`**

```python
"""Pydantic models internal to social signal computation.

Distinct from the API response models in app.models.social — these are
implementation-detail shapes used by classifier and scoring code.
"""
from __future__ import annotations

# Imports from pydantic + stdlib as needed.
# Paste verbatim: SocialSignalQueryProfile, SocialTextClassification,
# _OpenAIClassificationResponse.
```

- [ ] **Step 4: Create `normalize.py`**

```python
"""Pure string/timestamp/numeric normalization helpers.

No DB or HTTP calls.
"""
from __future__ import annotations

# Paste verbatim: _normalize_symbol, _normalize_keywords, _parse_timestamp,
# _json_default, _clip, _format_source, _source_failure_reason,
# _build_company_aliases.
```

- [ ] **Step 5: Create `classify.py`**

```python
"""Sentiment / topic classification — local rules + optional OpenAI."""
from __future__ import annotations

from app.services.social_signal.local_models import (
    SocialTextClassification,
    _OpenAIClassificationResponse,
)
from app.services.social_signal.normalize import _normalize_keywords  # if used

# Paste verbatim: _count_phrase_hits, _local_classify_text,
# _openai_classify_text_sync, _classify_text, _classify_posts, _classify_sources.
```

- [ ] **Step 6: Create `scoring.py`**

```python
"""Score computation: weights, aggregation, action mapping, market session."""
from __future__ import annotations

from app.services.social_signal.normalize import _clip  # if used

# Paste verbatim: _engagement_weight, _author_weight, _recency_weight,
# _sentiment_sign, _classify_confidence_label, _compute_market_score,
# _map_action, _downgrade_action, _serialize_snapshot, _aggregate_social_score,
# _compute_news_adjustment, is_market_session_open.
```

- [ ] **Step 7: Create `persistence.py`**

```python
"""DB-backed context loaders + execution gating + query profile builder."""
from __future__ import annotations

from app.services.social_signal.local_models import SocialSignalQueryProfile
from app.services.social_signal.normalize import (
    _build_company_aliases,
    _normalize_keywords,
    _normalize_symbol,
)

# Paste verbatim: build_query_profile, _load_positions_map,
# _load_signal_context_symbols, _count_today_executions,
# _latest_executed_snapshot_for_symbol, _ensure_social_auto_trade_allowed,
# _execute_signal_if_allowed.
```

- [ ] **Step 8: Create `runner.py`**

```python
"""Public entry points: score a symbol, list latest snapshots, run the monitor loop."""
from __future__ import annotations

from app.services.social_signal.classify import _classify_posts, _classify_sources
from app.services.social_signal.local_models import SocialSignalQueryProfile
from app.services.social_signal.normalize import (
    _format_source,
    _source_failure_reason,
)
from app.services.social_signal.persistence import (
    _execute_signal_if_allowed,
    _latest_executed_snapshot_for_symbol,
    _load_positions_map,
    _load_signal_context_symbols,
    build_query_profile,
)
from app.services.social_signal.scoring import (
    _aggregate_social_score,
    _compute_market_score,
    _compute_news_adjustment,
    _map_action,
    _downgrade_action,
    _serialize_snapshot,
    is_market_session_open,
)

# Paste verbatim: score_symbol_signal, get_latest_signals, run_social_monitor.
```

- [ ] **Step 9: Create `__init__.py`**

```python
"""Social signal scoring service package."""
from __future__ import annotations

from app.services.social_signal.local_models import (
    SocialSignalQueryProfile,
    SocialTextClassification,
)
from app.services.social_signal.persistence import build_query_profile
from app.services.social_signal.runner import (
    get_latest_signals,
    run_social_monitor,
    score_symbol_signal,
)
from app.services.social_signal.scoring import is_market_session_open

__all__ = [
    "SocialSignalQueryProfile",
    "SocialTextClassification",
    "build_query_profile",
    "get_latest_signals",
    "is_market_session_open",
    "run_social_monitor",
    "score_symbol_signal",
]
```

> If Step 1 turned up additional imported names (e.g. test files importing private helpers), append them to `__all__` and to the corresponding submodule import.

- [ ] **Step 10: Replace `social_signal_service.py` with a shim**

```python
"""Backward-compat shim. New code should import from app.services.social_signal directly."""
from app.services.social_signal import *  # noqa: F401, F403
from app.services.social_signal import __all__  # noqa: F401
```

- [ ] **Step 11: Run tests**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **60 passed**.

`tests/test_social_signal_service.py` is the largest pre-existing test (~30 tests). It is the most likely to break. Common fixes:
- Test imports `from app.services.social_signal_service import _foo` — either re-export `_foo` in the shim's `__all__` AND in the submodule `__init__.py`, OR update the test import path.
- Test monkeypatches `social_signal_service.bar = ...` — make sure `bar` exists as a re-export in the shim.

If you add private symbols to the shim, do it sparingly and only for things tests actually use.

- [ ] **Step 12: Commit**

```bash
git add backend/app/services/social_signal/ backend/app/services/social_signal_service.py
git commit -m "refactor: split social_signal_service.py into social_signal/ package"
```

---

## Task 6: Final verification + push

**Files:**
- Modify: `backend/tests/test_openapi_parity.py` (no change expected — sanity check only)

- [ ] **Step 1: Full test suite**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -v
```
Expected: **60 passed**, 0 deprecation warnings related to `on_event`.

- [ ] **Step 2: OpenAPI parity** (P0's lock should still hold)

```bash
pytest tests/test_openapi_parity.py -v
```
Expected: PASS.

- [ ] **Step 3: Live boot**

```bash
(uvicorn app.main:app --port 8765 > /tmp/uv.log 2>&1 &); sleep 3
for ep in /api/settings/status /api/social/providers /api/bot/status /api/strategies; do
  printf "%s -> " "$ep"
  curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765$ep"
done
pkill -f "uvicorn app.main:app --port 8765"; sleep 1
grep -E "ERROR|Exception" /tmp/uv.log | head
```
Expected: all four `200`, no errors in log.

- [ ] **Step 4: File-size sanity**

```bash
wc -l backend/app/main.py backend/app/database.py backend/app/services/monitoring_service.py backend/app/services/social_signal_service.py
```
Expected (rough):
- `main.py` ≈ 100-115 (lifespan migration may shift a few lines)
- `database.py` ≈ 2-3 (shim only)
- `monitoring_service.py` ≈ 2-3 (shim only)
- `social_signal_service.py` ≈ 2-3 (shim only)

```bash
find backend/app/models backend/app/db backend/app/services/monitoring backend/app/services/social_signal -name "*.py" | xargs wc -l | tail -20
```
No single submodule should be >400 lines.

- [ ] **Step 5: Push**

```bash
git push -u origin refactor/p1-structural-cleanup
```

---

## Done-criteria

- `pytest tests/` is fully green: **60 passed**, no `on_event` deprecation warnings.
- `app/models.py` is replaced by `app/models/` package (8 submodules + `__init__.py`).
- `app/database.py`, `app/services/monitoring_service.py`, `app/services/social_signal_service.py` are 2-3 line shims.
- New packages: `app/db/`, `app/services/monitoring/`, `app/services/social_signal/`.
- All existing import paths (`from app.models import X`, `from app.database import Trade`, `from app.services import monitoring_service`, etc.) still work.
- Live `uvicorn` boot returns 200 on the four spot-checked endpoints.
- Branch `refactor/p1-structural-cleanup` is pushed and ready to PR (stacks on top of `refactor/p0-router-split`).

After Phase 1 lands, **Phase 2 — Strategy framework** is unblocked: clean models, clean db, clean monitoring, and a stable lifespan for plugging in strategy registry boot.
