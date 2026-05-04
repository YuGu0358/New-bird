# Position Costs & Custom Stops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track per-(broker-account, ticker) cost basis (avg + total) and let the user set custom `stop_loss` / `take_profit` levels independent of any strategy.

**Architecture:** New `position_costs` SQLite table, single row per (broker_account_id, ticker). A buy event UPSERTs by recomputing `avg_cost = (old_total + new_qty*new_price) / (old_shares + new_qty)`. CRUD plus a dedicated `/buy` endpoint so the recompute logic stays in one place. Frontend exposes an editor panel triggered from `AccountDetailPage`.

**Tech Stack:** SQLAlchemy async + aiosqlite; FastAPI; pydantic v2; pytest with `asyncio_mode=auto`; React 18 + react-query v5.

---

## File Structure

**Create:**
- `backend/app/models/position_costs.py` — pydantic request/response models
- `backend/app/services/position_costs_service.py` — async CRUD + `record_buy` helper
- `backend/app/routers/position_costs.py` — REST surface
- `backend/tests/test_position_costs_service.py` — 7 tests
- `frontend-v2/src/components/PositionCostEditor.jsx` — modal-style form

**Modify:**
- `backend/app/db/tables.py` — add `PositionCost` ORM class
- `backend/app/db/engine.py` — `_apply_additive_migrations` adds the table for existing DBs
- `backend/app/main.py` — register router (alphabetical with the other Tradewell routers)
- `backend/app/models/__init__.py` — re-export new pydantic models
- `backend/tests/test_openapi_parity.py` — add 5 new routes
- `frontend-v2/src/lib/api.js` — extend with 5 helpers
- `frontend-v2/src/pages/AccountDetailPage.jsx` — render edit panel per row

---

## Reference: Existing Code to Read Before Starting

1. `backend/app/services/position_overrides_service.py` — same shape: per-(account, ticker) row with custom levels. Mirror its CRUD style.
2. `backend/app/services/workspace_service.py:55-84` — INSERT ON CONFLICT DO UPDATE pattern for upserts.
3. `backend/app/db/engine.py:_apply_additive_migrations` — pattern for adding columns/tables to existing DBs without dropping data.
4. `backend/tests/test_workspace.py` — fixture pattern that points the engine at a fresh tmp SQLite per test.
5. `backend/app/dependencies.py` — `SessionDep` and `service_error` exports.

---

## Tasks

### Task 1: Add `PositionCost` ORM table + migration

**Files:**
- Modify: `backend/app/db/tables.py`
- Modify: `backend/app/db/engine.py`

- [ ] **Step 1: Read the existing PositionOverride table for style reference**

```bash
grep -A 25 "class PositionOverride" backend/app/db/tables.py
```

- [ ] **Step 2: Append the PositionCost class to backend/app/db/tables.py**

After the `PositionOverride` class:

```python
class PositionCost(Base):
    """Per-(broker_account, ticker) cost basis + user-set protective levels.

    A buy event UPSERTs the row by recomputing avg_cost from the old
    aggregate plus the new fill. Sells reduce shares; we keep the same
    avg_cost (FIFO is out of scope for the MVP).
    """

    __tablename__ = "position_costs"
    __table_args__ = (
        UniqueConstraint("broker_account_id", "ticker", name="uq_position_costs_account_ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    broker_account_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    avg_cost_basis: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_shares: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    custom_stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    custom_take_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
```

Verify `UniqueConstraint`, `Optional`, `Float`, `Text` are imported at the top — they likely already are.

- [ ] **Step 3: Verify create_all picks up the new table**

```bash
cd /Users/yugu/NewBirdClaude/backend
source .venv/bin/activate
python -c "
import asyncio
from app.db import init_database, AsyncSessionLocal
from sqlalchemy import text
async def check():
    await init_database()
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text('PRAGMA table_info(position_costs)'))).fetchall()
        print([r[1] for r in rows])
asyncio.run(check())
"
```

Expected: `['id', 'broker_account_id', 'ticker', 'avg_cost_basis', 'total_shares', 'custom_stop_loss', 'custom_take_profit', 'notes', 'created_at', 'updated_at']`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/tables.py
git commit -m "feat(position-costs): add position_costs ORM table"
```

---

### Task 2: Pydantic models

**Files:**
- Create: `backend/app/models/position_costs.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create the models file**

```python
"""Pydantic models for the position_costs surface."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PositionCostView(BaseModel):
    """Wire shape returned by GET / list / upsert endpoints."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    broker_account_id: int
    ticker: str
    avg_cost_basis: float
    total_shares: float
    custom_stop_loss: Optional[float] = None
    custom_take_profit: Optional[float] = None
    notes: str = ""
    created_at: datetime
    updated_at: datetime


class PositionCostListResponse(BaseModel):
    items: list[PositionCostView]


class PositionCostUpsertRequest(BaseModel):
    """Manual override / set-once form. Use /buy for incremental buys."""

    broker_account_id: int = Field(..., gt=0)
    ticker: str = Field(..., min_length=1, max_length=16)
    avg_cost_basis: float = Field(..., ge=0)
    total_shares: float = Field(..., ge=0)
    custom_stop_loss: Optional[float] = Field(None, ge=0)
    custom_take_profit: Optional[float] = Field(None, ge=0)
    notes: str = ""


class PositionCostBuyRequest(BaseModel):
    """Record a new buy fill; service recomputes avg_cost."""

    broker_account_id: int = Field(..., gt=0)
    ticker: str = Field(..., min_length=1, max_length=16)
    fill_price: float = Field(..., gt=0)
    fill_qty: float = Field(..., gt=0)
```

- [ ] **Step 2: Re-export from app/models/__init__.py**

In the long imports block, append a strategies-style block (alphabetical with neighbors):

```python
from app.models.position_costs import (
    PositionCostBuyRequest,
    PositionCostListResponse,
    PositionCostUpsertRequest,
    PositionCostView,
)
```

And in `__all__`:

```
    "PositionCostBuyRequest",
    "PositionCostListResponse",
    "PositionCostUpsertRequest",
    "PositionCostView",
```

- [ ] **Step 3: Verify imports work**

```bash
python -c "from app.models import PositionCostView, PositionCostUpsertRequest, PositionCostBuyRequest, PositionCostListResponse; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/position_costs.py backend/app/models/__init__.py
git commit -m "feat(position-costs): pydantic models"
```

---

### Task 3: Service layer with TDD

**Files:**
- Create: `backend/tests/test_position_costs_service.py`
- Create: `backend/app/services/position_costs_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_position_costs_service.py`:

```python
"""Service-level tests for position_costs (cost basis + custom stops)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp SQLite per test (mirrors test_workspace.py)."""
    import importlib
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine_module = importlib.import_module("app.db.engine")
    from app.database import AsyncSessionLocal

    original_engine = engine_module.engine
    db_path = tmp_path / "position_costs.db"
    new_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", echo=False, future=True
    )
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)
    AsyncSessionLocal.configure(bind=new_engine)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    AsyncSessionLocal.configure(bind=original_engine)
    await new_engine.dispose()


async def _session():
    from app.database import AsyncSessionLocal
    return AsyncSessionLocal()


@pytest.mark.asyncio
async def test_list_empty_returns_zero_rows() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        result = await position_costs_service.list_for_account(s, broker_account_id=1)
    assert result == []


@pytest.mark.asyncio
async def test_record_buy_creates_row_with_avg_equal_to_fill_price() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        view = await position_costs_service.record_buy(
            s, broker_account_id=1, ticker="NVDA", fill_price=180.0, fill_qty=10.0,
        )
    assert view["avg_cost_basis"] == 180.0
    assert view["total_shares"] == 10.0


@pytest.mark.asyncio
async def test_record_buy_recomputes_avg_on_second_buy() -> None:
    """First buy 10 @ 180. Second buy 10 @ 200. New avg = 190."""
    from app.services import position_costs_service
    async with await _session() as s:
        await position_costs_service.record_buy(
            s, broker_account_id=1, ticker="NVDA", fill_price=180.0, fill_qty=10.0,
        )
        view = await position_costs_service.record_buy(
            s, broker_account_id=1, ticker="NVDA", fill_price=200.0, fill_qty=10.0,
        )
    assert view["avg_cost_basis"] == pytest.approx(190.0)
    assert view["total_shares"] == 20.0


@pytest.mark.asyncio
async def test_upsert_replaces_avg_directly() -> None:
    """Manual upsert bypasses the running average — used to import existing positions."""
    from app.services import position_costs_service
    async with await _session() as s:
        await position_costs_service.upsert(
            s, broker_account_id=1, ticker="AAPL",
            avg_cost_basis=150.0, total_shares=20.0,
            custom_stop_loss=140.0, custom_take_profit=180.0, notes="imported",
        )
        view = await position_costs_service.get_one(s, broker_account_id=1, ticker="AAPL")
    assert view is not None
    assert view["avg_cost_basis"] == 150.0
    assert view["custom_stop_loss"] == 140.0
    assert view["notes"] == "imported"


@pytest.mark.asyncio
async def test_get_one_returns_none_when_missing() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        view = await position_costs_service.get_one(s, broker_account_id=1, ticker="GHOST")
    assert view is None


@pytest.mark.asyncio
async def test_delete_returns_true_when_existed() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        await position_costs_service.record_buy(
            s, broker_account_id=1, ticker="NVDA", fill_price=180.0, fill_qty=10.0,
        )
        deleted = await position_costs_service.delete(s, broker_account_id=1, ticker="NVDA")
    assert deleted is True


@pytest.mark.asyncio
async def test_delete_returns_false_when_absent() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        deleted = await position_costs_service.delete(s, broker_account_id=1, ticker="GHOST")
    assert deleted is False
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
python -m pytest tests/test_position_costs_service.py -q
```

Expected: 7 errors with `ModuleNotFoundError: No module named 'app.services.position_costs_service'`.

- [ ] **Step 3: Create the service**

```python
"""CRUD service for position_costs.

A buy event recomputes avg_cost from the running aggregate; sells are
out of scope for the MVP (FIFO/LIFO accounting needs trade-by-trade
history we don't track here).

The `upsert` form lets the user import an existing position by setting
avg_cost + total_shares directly, bypassing the running-average math.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import PositionCost


def _serialize(row: PositionCost) -> dict[str, Any]:
    return {
        "id": row.id,
        "broker_account_id": row.broker_account_id,
        "ticker": row.ticker,
        "avg_cost_basis": float(row.avg_cost_basis),
        "total_shares": float(row.total_shares),
        "custom_stop_loss": (
            float(row.custom_stop_loss) if row.custom_stop_loss is not None else None
        ),
        "custom_take_profit": (
            float(row.custom_take_profit) if row.custom_take_profit is not None else None
        ),
        "notes": row.notes or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def list_for_account(
    session: AsyncSession, *, broker_account_id: int
) -> list[dict[str, Any]]:
    stmt = (
        select(PositionCost)
        .where(PositionCost.broker_account_id == broker_account_id)
        .order_by(PositionCost.ticker)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


async def get_one(
    session: AsyncSession, *, broker_account_id: int, ticker: str
) -> Optional[dict[str, Any]]:
    stmt = select(PositionCost).where(
        PositionCost.broker_account_id == broker_account_id,
        PositionCost.ticker == ticker.upper(),
    )
    row = (await session.execute(stmt)).scalars().first()
    return _serialize(row) if row is not None else None


async def upsert(
    session: AsyncSession,
    *,
    broker_account_id: int,
    ticker: str,
    avg_cost_basis: float,
    total_shares: float,
    custom_stop_loss: Optional[float] = None,
    custom_take_profit: Optional[float] = None,
    notes: str = "",
) -> dict[str, Any]:
    """Direct upsert — replaces avg/shares wholesale (use record_buy for incremental)."""
    now = datetime.now(timezone.utc)
    stmt = sqlite_insert(PositionCost).values(
        broker_account_id=broker_account_id,
        ticker=ticker.upper(),
        avg_cost_basis=avg_cost_basis,
        total_shares=total_shares,
        custom_stop_loss=custom_stop_loss,
        custom_take_profit=custom_take_profit,
        notes=notes,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PositionCost.broker_account_id, PositionCost.ticker],
        set_={
            "avg_cost_basis": avg_cost_basis,
            "total_shares": total_shares,
            "custom_stop_loss": custom_stop_loss,
            "custom_take_profit": custom_take_profit,
            "notes": notes,
            "updated_at": now,
        },
    )
    await session.execute(stmt)
    await session.commit()
    fetched = await get_one(session, broker_account_id=broker_account_id, ticker=ticker)
    assert fetched is not None
    return fetched


async def record_buy(
    session: AsyncSession,
    *,
    broker_account_id: int,
    ticker: str,
    fill_price: float,
    fill_qty: float,
) -> dict[str, Any]:
    """Record a buy; recompute the running average cost basis."""
    if fill_price <= 0 or fill_qty <= 0:
        raise ValueError("fill_price and fill_qty must be positive")

    existing = await get_one(
        session, broker_account_id=broker_account_id, ticker=ticker
    )

    if existing is None:
        new_avg = fill_price
        new_shares = fill_qty
    else:
        old_total = existing["avg_cost_basis"] * existing["total_shares"]
        new_total_cost = old_total + fill_price * fill_qty
        new_shares = existing["total_shares"] + fill_qty
        new_avg = new_total_cost / new_shares if new_shares > 0 else 0.0

    return await upsert(
        session,
        broker_account_id=broker_account_id,
        ticker=ticker,
        avg_cost_basis=new_avg,
        total_shares=new_shares,
        custom_stop_loss=(existing or {}).get("custom_stop_loss"),
        custom_take_profit=(existing or {}).get("custom_take_profit"),
        notes=(existing or {}).get("notes", ""),
    )


async def delete(
    session: AsyncSession, *, broker_account_id: int, ticker: str
) -> bool:
    stmt = select(PositionCost).where(
        PositionCost.broker_account_id == broker_account_id,
        PositionCost.ticker == ticker.upper(),
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
```

- [ ] **Step 4: Run tests — expect green**

```bash
python -m pytest tests/test_position_costs_service.py -q
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/position_costs_service.py backend/tests/test_position_costs_service.py
git commit -m "feat(position-costs): service layer with running-avg cost"
```

---

### Task 4: REST router + OpenAPI parity

**Files:**
- Create: `backend/app/routers/position_costs.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: Create the router**

```python
"""REST surface for position_costs."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    PositionCostBuyRequest,
    PositionCostListResponse,
    PositionCostUpsertRequest,
    PositionCostView,
)
from app.services import position_costs_service

router = APIRouter(prefix="/api/position-costs", tags=["position-costs"])


@router.get("", response_model=PositionCostListResponse)
async def list_costs(broker_account_id: int, session: SessionDep) -> PositionCostListResponse:
    try:
        items = await position_costs_service.list_for_account(
            session, broker_account_id=broker_account_id
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return PositionCostListResponse(items=[PositionCostView(**i) for i in items])


@router.get("/{broker_account_id}/{ticker}", response_model=PositionCostView)
async def get_cost(broker_account_id: int, ticker: str, session: SessionDep) -> PositionCostView:
    try:
        view = await position_costs_service.get_one(
            session, broker_account_id=broker_account_id, ticker=ticker
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if view is None:
        raise HTTPException(status_code=404, detail="Position cost not found")
    return PositionCostView(**view)


@router.put("", response_model=PositionCostView)
async def upsert_cost(request: PositionCostUpsertRequest, session: SessionDep) -> PositionCostView:
    try:
        view = await position_costs_service.upsert(
            session,
            broker_account_id=request.broker_account_id,
            ticker=request.ticker,
            avg_cost_basis=request.avg_cost_basis,
            total_shares=request.total_shares,
            custom_stop_loss=request.custom_stop_loss,
            custom_take_profit=request.custom_take_profit,
            notes=request.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PositionCostView(**view)


@router.post("/buy", response_model=PositionCostView)
async def record_buy(request: PositionCostBuyRequest, session: SessionDep) -> PositionCostView:
    try:
        view = await position_costs_service.record_buy(
            session,
            broker_account_id=request.broker_account_id,
            ticker=request.ticker,
            fill_price=request.fill_price,
            fill_qty=request.fill_qty,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PositionCostView(**view)


@router.delete("/{broker_account_id}/{ticker}", status_code=204)
async def delete_cost(broker_account_id: int, ticker: str, session: SessionDep) -> None:
    try:
        deleted = await position_costs_service.delete(
            session, broker_account_id=broker_account_id, ticker=ticker
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Position cost not found")
    return None
```

- [ ] **Step 2: Wire in main.py**

Add the import alphabetically:
```python
from app.routers import position_costs as position_costs_router
```

In the include block (Tradewell section), after `portfolio_overrides_router`:
```python
app.include_router(position_costs_router.router)
```

- [ ] **Step 3: Add OpenAPI parity entries**

In `backend/tests/test_openapi_parity.py`, append:
```python
    # --- Position costs (cost basis + custom stops) ---
    ("GET",    "/api/position-costs"),
    ("PUT",    "/api/position-costs"),
    ("GET",    "/api/position-costs/{broker_account_id}/{ticker}"),
    ("DELETE", "/api/position-costs/{broker_account_id}/{ticker}"),
    ("POST",   "/api/position-costs/buy"),
```

- [ ] **Step 4: Run parity test + full suite**

```bash
python -m pytest tests/test_openapi_parity.py -q
python -m pytest -q
```

Expected: parity passes; full suite previous count + 7 new = green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/position_costs.py backend/app/main.py backend/tests/test_openapi_parity.py
git commit -m "feat(position-costs): REST router + OpenAPI parity"
```

---

### Task 5: Frontend API client

**Files:**
- Modify: `frontend-v2/src/lib/api.js`

- [ ] **Step 1: Add the helpers**

After the existing `position overrides` section in `frontend-v2/src/lib/api.js`, append:

```javascript
// ----------------------------------------------------------- position costs (cost basis + custom stops)
/** @param {number} accountPk */
export const listPositionCosts = (accountPk) =>
  request(`/api/position-costs?broker_account_id=${accountPk}`);

/** @param {number} accountPk @param {string} ticker */
export const getPositionCost = (accountPk, ticker) =>
  request(`/api/position-costs/${accountPk}/${encodeURIComponent(ticker)}`);

/**
 * @param {{ broker_account_id: number, ticker: string, avg_cost_basis: number,
 *           total_shares: number, custom_stop_loss?: number|null,
 *           custom_take_profit?: number|null, notes?: string }} payload
 */
export const upsertPositionCost = (payload) =>
  request('/api/position-costs', { method: 'PUT', body: payload });

/** @param {{ broker_account_id: number, ticker: string, fill_price: number, fill_qty: number }} payload */
export const recordPositionBuy = (payload) =>
  request('/api/position-costs/buy', { method: 'POST', body: payload });

/** @param {number} accountPk @param {string} ticker */
export const deletePositionCost = (accountPk, ticker) =>
  request(`/api/position-costs/${accountPk}/${encodeURIComponent(ticker)}`, { method: 'DELETE' });
```

- [ ] **Step 2: Build to verify**

```bash
cd /Users/yugu/NewBirdClaude/frontend-v2 && npm run build 2>&1 | tail -8
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend-v2/src/lib/api.js
git commit -m "feat(position-costs): frontend api helpers"
```

---

### Task 6: PositionCostEditor component

**Files:**
- Create: `frontend-v2/src/components/PositionCostEditor.jsx`

- [ ] **Step 1: Create the component**

```jsx
// PositionCostEditor — inline form for setting cost basis + custom stops on
// one (broker_account, ticker) pair. Used inside AccountDetailPage rows.
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Save, Trash2, X } from 'lucide-react';
import {
  deletePositionCost,
  getPositionCost,
  recordPositionBuy,
  upsertPositionCost,
} from '../lib/api.js';
import { ErrorState, LoadingState } from './primitives.jsx';

/**
 * @param {{ accountPk: number, ticker: string, onClose?: () => void }} props
 */
export default function PositionCostEditor({ accountPk, ticker, onClose }) {
  const queryClient = useQueryClient();
  const ctxQ = useQuery({
    queryKey: ['position-cost', accountPk, ticker],
    queryFn: () => getPositionCost(accountPk, ticker),
    retry: false,
  });

  const isNotFound = ctxQ.isError && /** @type {any} */ (ctxQ.error)?.status === 404;
  const existing = isNotFound || ctxQ.isLoading ? null : /** @type {any} */ (ctxQ.data);

  const [avgCost, setAvgCost] = useState('');
  const [totalShares, setTotalShares] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [takeProfit, setTakeProfit] = useState('');
  const [notes, setNotes] = useState('');
  const [buyPrice, setBuyPrice] = useState('');
  const [buyQty, setBuyQty] = useState('');

  useEffect(() => {
    if (existing) {
      setAvgCost(String(existing.avg_cost_basis ?? ''));
      setTotalShares(String(existing.total_shares ?? ''));
      setStopLoss(existing.custom_stop_loss != null ? String(existing.custom_stop_loss) : '');
      setTakeProfit(existing.custom_take_profit != null ? String(existing.custom_take_profit) : '');
      setNotes(existing.notes ?? '');
    } else if (isNotFound) {
      setAvgCost(''); setTotalShares(''); setStopLoss(''); setTakeProfit(''); setNotes('');
    }
  }, [existing, isNotFound]);

  const invalidate = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['position-cost', accountPk, ticker] }),
    queryClient.invalidateQueries({ queryKey: ['position-costs', accountPk] }),
  ]);

  const upsertMut = useMutation({
    mutationFn: () => upsertPositionCost({
      broker_account_id: accountPk, ticker,
      avg_cost_basis: Number.parseFloat(avgCost) || 0,
      total_shares: Number.parseFloat(totalShares) || 0,
      custom_stop_loss: stopLoss === '' ? null : Number.parseFloat(stopLoss),
      custom_take_profit: takeProfit === '' ? null : Number.parseFloat(takeProfit),
      notes,
    }),
    onSuccess: async () => { await invalidate(); },
  });
  const buyMut = useMutation({
    mutationFn: () => recordPositionBuy({
      broker_account_id: accountPk, ticker,
      fill_price: Number.parseFloat(buyPrice),
      fill_qty: Number.parseFloat(buyQty),
    }),
    onSuccess: async () => {
      await invalidate();
      setBuyPrice(''); setBuyQty('');
    },
  });
  const deleteMut = useMutation({
    mutationFn: () => deletePositionCost(accountPk, ticker),
    onSuccess: async () => {
      await invalidate();
      if (onClose) onClose();
    },
  });

  if (ctxQ.isLoading) return <LoadingState rows={3} />;
  if (ctxQ.isError && !isNotFound) return <ErrorState error={ctxQ.error} onRetry={ctxQ.refetch} />;

  return (
    <div className="border border-border-subtle p-4 space-y-3 bg-elevated">
      <div className="flex items-baseline justify-between">
        <div className="font-mono text-[11px] tracking-[0.15em] uppercase text-text-muted">
          Cost basis · {ticker}
        </div>
        {onClose && (
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X size={14} /></button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Avg cost basis" value={avgCost} onChange={setAvgCost} placeholder="180.00" />
        <Field label="Total shares" value={totalShares} onChange={setTotalShares} placeholder="10" />
        <Field label="Custom stop-loss" value={stopLoss} onChange={setStopLoss} placeholder="—" />
        <Field label="Custom take-profit" value={takeProfit} onChange={setTakeProfit} placeholder="—" />
      </div>
      <div>
        <FieldLabel>Notes</FieldLabel>
        <textarea className="input min-h-[64px]" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </div>

      <div className="flex items-center gap-2">
        <button className="btn-primary btn-sm inline-flex items-center gap-1"
          onClick={() => upsertMut.mutate()} disabled={upsertMut.isPending}>
          <Save size={12} /> Save
        </button>
        {existing && (
          <button className="btn-destructive btn-sm inline-flex items-center gap-1"
            onClick={() => {
              if (typeof window !== 'undefined' && window.confirm(`Clear cost basis for ${ticker}?`)) {
                deleteMut.mutate();
              }
            }}
            disabled={deleteMut.isPending}>
            <Trash2 size={12} /> Clear
          </button>
        )}
      </div>

      <div className="border-t border-border-subtle pt-3">
        <FieldLabel>Record a buy (auto-recomputes avg)</FieldLabel>
        <div className="grid grid-cols-3 gap-2">
          <input className="input" type="number" step="0.01" placeholder="Fill price"
            value={buyPrice} onChange={(e) => setBuyPrice(e.target.value)} />
          <input className="input" type="number" step="0.0001" placeholder="Fill qty"
            value={buyQty} onChange={(e) => setBuyQty(e.target.value)} />
          <button className="btn-secondary btn-sm"
            onClick={() => buyMut.mutate()}
            disabled={buyMut.isPending || !buyPrice || !buyQty}>
            Add buy
          </button>
        </div>
      </div>

      {(upsertMut.isError || buyMut.isError || deleteMut.isError) && (
        <div className="mt-2"><ErrorState error={upsertMut.error || buyMut.error || deleteMut.error} /></div>
      )}
    </div>
  );
}

function Field({ label, value, onChange, placeholder }) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <input type="number" step="0.01" className="input tabular"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

function FieldLabel({ children }) {
  return (
    <div className="font-mono text-[10px] text-text-muted tracking-[0.15em] uppercase mb-1">
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Build**

```bash
cd frontend-v2 && npm run build 2>&1 | tail -5
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend-v2/src/components/PositionCostEditor.jsx
git commit -m "feat(position-costs): PositionCostEditor component"
```

---

### Task 7: Wire editor into AccountDetailPage

**Files:**
- Modify: `frontend-v2/src/pages/AccountDetailPage.jsx`

- [ ] **Step 1: Add imports + state + button**

1. Add to the existing imports at the top:
```javascript
import PositionCostEditor from '../components/PositionCostEditor.jsx';
```

2. Inside the page component, add state:
```javascript
const [costEditorTicker, setCostEditorTicker] = useState(null);
```

3. In each position row's actions area (next to the existing override edit trigger), add:
```jsx
<button className="btn-secondary btn-sm" onClick={() => setCostEditorTicker(row.symbol)}>
  Cost
</button>
```

4. Below the row when `costEditorTicker === row.symbol`, render:
```jsx
{costEditorTicker === row.symbol && (
  <div className="mt-3">
    <PositionCostEditor
      accountPk={Number(id)}
      ticker={row.symbol}
      onClose={() => setCostEditorTicker(null)}
    />
  </div>
)}
```

- [ ] **Step 2: Build**

```bash
cd frontend-v2 && npm run build 2>&1 | tail -5
```

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend-v2/src/pages/AccountDetailPage.jsx
git commit -m "feat(position-costs): wire editor into AccountDetailPage"
```

---

### Task 8: Final verification

- [ ] **Step 1: Backend tests**
```bash
cd backend && source .venv/bin/activate
python -m pytest -q
```
Expected: previous count + 7 new = green.

- [ ] **Step 2: Frontend build**
```bash
cd ../frontend-v2 && npm run build 2>&1 | tail -8
```
Expected: clean build.

- [ ] **Step 3: Smoke test the new endpoint**
```bash
curl -X PUT http://127.0.0.1:8000/api/position-costs \
  -H 'Content-Type: application/json' \
  -d '{"broker_account_id":1,"ticker":"NVDA","avg_cost_basis":180,"total_shares":10,"custom_stop_loss":160,"custom_take_profit":220,"notes":"manual import"}' \
  -o /tmp/_pc.json -w "HTTP %{http_code}\n"

curl http://127.0.0.1:8000/api/position-costs?broker_account_id=1
```
Expected: HTTP 200 then a list including the new row.

---

## Self-Review Checklist

- [ ] Unique constraint on `(broker_account_id, ticker)` so the upsert pattern works.
- [ ] `record_buy` actually computes `(old_total + new_qty*new_price) / (old_shares + new_qty)`, not a simple two-average mean.
- [ ] All 5 routes in OpenAPI parity test.
- [ ] DELETE returns 204 (FastAPI default for explicit `status_code=204`).
- [ ] Frontend uses `encodeURIComponent` on every `{ticker}` path param.

---

## Follow-Ups (out of scope)

1. Sells / FIFO accounting — needs a `position_buy_lots` table to track individual fills.
2. Surface unrealized P&L in the editor by passing `currentPrice` as a prop.
3. Trigger a notification when current price crosses `custom_stop_loss` or `custom_take_profit` — feeds into the Trade Recommendation plan.
