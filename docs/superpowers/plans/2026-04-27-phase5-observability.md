# Phase 5 — Observability + Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the last backend gap before frontend redesign — give the system the observability surface a real quant platform needs:

1. **Daily PnL aggregator** computed from the `Trade` table → closes the P4 stub where `MaxDailyLossPolicy` always saw `realized_pnl_today = 0.0`. Now the daily-loss circuit breaker actually works in production.
2. **Strategy health endpoint** (`/api/strategy/health`) — aggregated read of "today's PnL, trades today, open positions, last trade timestamp, win/loss streak" so the UI (or a CLI / Slackbot) can answer "is the bot healthy right now?" in one call.
3. **Structured logging** — ContextVar-scoped correlation ID + JSON line formatter so production logs can be grepped by run, strategy, or symbol.
4. **Health probes** — `/api/health` (liveness, never depends on external services), `/api/health/ready` (readiness — DB writable + active strategy resolvable).
5. **Metrics endpoint** — Prometheus-compatible plain-text `/metrics` exposing in-process counters/gauges (HTTP requests, risk events, backtest runs, strategy ticks). Hand-rolled, no new top-level dependency.
6. **Notifications service** — minimal webhook delivery hooked into `risk_service.record_event` so a Slack / Discord / generic webhook URL gets pinged when the bot's risk layer rejects an order. Email and other channels deferred.

**Architecture:**

```
                    Strategy B / Backtest
                           │ submit_order
                           ▼
                    ┌────────────┐
                    │ RiskGuard  │ ── deny ──► risk_service.record_event ──► RiskEvent
                    └─────┬──────┘                                              │
                          │ allow                                               │
                          ▼                                                     ▼
                    Broker (alpaca/backtest)                              notifications_service
                                                                                │
                                                                           webhook POST
                                                                                ▼
                                                                          Slack/Discord/etc

  GET /api/strategy/health   ─── reads ──►  Trade table + alpaca_service positions
  GET /api/health           ─── liveness probe (no DB)
  GET /api/health/ready     ─── readiness probe (DB ping + registry resolves)
  GET /metrics              ─── Prometheus exposition format
```

**Tech Stack:** Python 3.13, FastAPI 0.135, SQLAlchemy async + aiosqlite, `httpx` (already a dep) for webhook delivery. **No new top-level dependencies.**

**Out of scope (deferred):**
- Multi-channel notifications (email, SMS, push) — webhook-only in Phase 5.
- OpenTelemetry tracing, Sentry integration — future phase if needed.
- Frontend rendering of strategy health / metrics dashboards — frozen until backend done.
- Daily-loss reset semantics around DST / non-UTC — Phase 5 uses UTC start-of-day.
- Long-running cron / scheduled aggregations — `/api/strategy/health` computes on-demand.
- Per-strategy or per-broker metric labels — global counters only.

---

## File Structure

### New packages
| Path | Responsibility |
|---|---|
| `backend/core/observability/__init__.py` | Re-exports |
| `backend/core/observability/correlation.py` | ContextVar-based correlation-id store + helpers |
| `backend/core/observability/logging_setup.py` | JSON line formatter + `configure_logging()` |
| `backend/core/observability/metrics.py` | Hand-rolled Counter / Gauge / Histogram + `render_prometheus()` |

### New services + routers
| Path | Responsibility |
|---|---|
| `backend/app/services/pnl_service.py` | Aggregate Trade table → daily / window PnL + win/loss streak |
| `backend/app/services/notifications_service.py` | Webhook delivery via httpx |
| `backend/app/middleware/correlation.py` | ASGI middleware that mints/picks up correlation IDs |
| `backend/app/middleware/metrics.py` | ASGI middleware that increments request counters / latency |
| `backend/app/routers/health.py` | `/api/health` + `/api/health/ready` |
| `backend/app/routers/metrics.py` | `/metrics` (note: NOT `/api/metrics`, Prometheus convention) |
| `backend/app/routers/strategy_health.py` | `/api/strategy/health` (aggregated bot status) |

### Modified files
| File | Change |
|---|---|
| `backend/app/main.py` | Call `configure_logging()` at import time. Add the two middlewares. Register `health_router`, `metrics_router`, `strategy_health_router`. |
| `backend/app/services/risk_service.py` | After `record_event`, fire-and-forget `notifications_service.dispatch_risk_event(event)`. |
| `backend/strategy/runner.py` | Live snapshot now calls `pnl_service.realized_pnl_today()` to populate `realized_pnl_today` (was 0.0). |
| `backend/core/backtest/engine.py` | Backtest snapshot provider populates `realized_pnl_today` from the running portfolio's same-day fills. |
| `backend/app/runtime_settings.py` | Register a new optional setting `NOTIFICATIONS_WEBHOOK_URL` (read by notifications_service). |
| `backend/app/models/__init__.py` | Re-export new API models. |
| `backend/tests/test_openapi_parity.py` | Add 4 new routes (`/api/health`, `/api/health/ready`, `/metrics`, `/api/strategy/health`). |

### New API models
| Path | Models |
|---|---|
| `backend/app/models/observability.py` | `HealthResponse`, `ReadinessResponse`, `StrategyHealthResponse` |

### New tests
| Path | What it covers |
|---|---|
| `backend/tests/test_pnl_service.py` | PnL aggregation: empty / mixed / pre-today filtered / streak calculation |
| `backend/tests/test_correlation.py` | ContextVar set/get, middleware mints UUID when no header, picks up `X-Request-ID` when present |
| `backend/tests/test_metrics.py` | Counter increments, gauge set/inc, histogram bucket placement, `render_prometheus()` text |
| `backend/tests/test_notifications.py` | Webhook payload shape, missing URL → silent skip, httpx error → silent (no raise) |
| `backend/tests/test_app_smoke.py` (append) | `/api/health`, `/api/health/ready`, `/metrics`, `/api/strategy/health` |

### Untouched
- All Phase 0–4 work unless explicitly modified.
- Strategy B trading logic.
- Frontend, agent-harness, launcher, Dockerfile, CI workflows.

---

## Pre-flight

- [ ] Confirm baseline (we end Phase 4 at 111 passed):
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **111 passed**.

- [ ] Branch off P4:
```bash
cd ~/NewBirdClaude
git checkout feat/p4-risk-layer
git checkout -b feat/p5-observability
```

---

## Task 1: Daily PnL aggregator (TDD)

**Files:**
- Create: `backend/app/services/pnl_service.py`
- Create: `backend/tests/test_pnl_service.py`

The `Trade` table stores closed round-trips (`net_profit`, `exit_date`). Phase 5 reads it to compute today's realized PnL in UTC, plus a win/loss streak.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_pnl_service.py
"""PnL aggregation from the Trade table."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database import AsyncSessionLocal, Trade, init_database
from app.services import pnl_service


@pytest.fixture(autouse=True)
async def _isolate_trades(monkeypatch, tmp_path):
    """Each test runs against a fresh tmp DB so Trade rows don't leak."""
    from app.db import engine as engine_module
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    db_path = tmp_path / "p5.db"
    new_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, future=True)
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    # Re-export shim attributes:
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    await new_engine.dispose()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_realized_pnl_today_zero_when_no_trades() -> None:
    async with AsyncSessionLocal() as session:
        result = await pnl_service.realized_pnl_today(session)
    assert result == 0.0


@pytest.mark.asyncio
async def test_realized_pnl_today_sums_today_only() -> None:
    today = _now_utc()
    yesterday = today - timedelta(days=1)
    async with AsyncSessionLocal() as session:
        session.add(Trade(symbol="AAPL", entry_date=today, exit_date=today, entry_price=100, exit_price=110, qty=10, net_profit=100.0, exit_reason="TAKE_PROFIT"))
        session.add(Trade(symbol="MSFT", entry_date=yesterday, exit_date=yesterday, entry_price=400, exit_price=380, qty=5, net_profit=-100.0, exit_reason="STOP_LOSS"))
        session.add(Trade(symbol="NVDA", entry_date=today, exit_date=today, entry_price=900, exit_price=850, qty=2, net_profit=-100.0, exit_reason="STOP_LOSS"))
        await session.commit()
        result = await pnl_service.realized_pnl_today(session)
    # Today: +100 (AAPL) - 100 (NVDA) = 0. Yesterday's -100 (MSFT) excluded.
    assert result == 0.0


@pytest.mark.asyncio
async def test_realized_pnl_today_returns_negative_when_losing() -> None:
    today = _now_utc()
    async with AsyncSessionLocal() as session:
        session.add(Trade(symbol="AAPL", entry_date=today, exit_date=today, entry_price=100, exit_price=90, qty=10, net_profit=-100.0, exit_reason="STOP_LOSS"))
        session.add(Trade(symbol="MSFT", entry_date=today, exit_date=today, entry_price=400, exit_price=380, qty=5, net_profit=-100.0, exit_reason="STOP_LOSS"))
        await session.commit()
        result = await pnl_service.realized_pnl_today(session)
    assert result == -200.0


@pytest.mark.asyncio
async def test_summary_returns_aggregated_stats() -> None:
    today = _now_utc()
    yesterday = today - timedelta(days=1)
    async with AsyncSessionLocal() as session:
        session.add(Trade(symbol="AAPL", entry_date=today, exit_date=today, entry_price=100, exit_price=110, qty=10, net_profit=100.0, exit_reason="TAKE_PROFIT"))
        session.add(Trade(symbol="MSFT", entry_date=today, exit_date=today, entry_price=400, exit_price=380, qty=5, net_profit=-100.0, exit_reason="STOP_LOSS"))
        session.add(Trade(symbol="GOOG", entry_date=yesterday, exit_date=yesterday, entry_price=150, exit_price=160, qty=3, net_profit=30.0, exit_reason="TAKE_PROFIT"))
        await session.commit()
        summary = await pnl_service.daily_summary(session)
    assert summary["realized_pnl_today"] == 0.0
    assert summary["trades_today"] == 2
    assert summary["wins_today"] == 1
    assert summary["losses_today"] == 1
    assert summary["last_trade_at"] is not None


@pytest.mark.asyncio
async def test_recent_streak_counts_consecutive_outcomes() -> None:
    base = _now_utc() - timedelta(days=3)
    async with AsyncSessionLocal() as session:
        # Older first → newer last so the streak is "two losses ending today".
        for i, pnl in enumerate([50.0, 50.0, -10.0, -20.0]):
            ts = base + timedelta(hours=i)
            session.add(Trade(
                symbol="X", entry_date=ts, exit_date=ts,
                entry_price=10, exit_price=10 + pnl / 1, qty=1,
                net_profit=pnl, exit_reason="TAKE_PROFIT" if pnl > 0 else "STOP_LOSS",
            ))
        await session.commit()
        streak = await pnl_service.recent_streak(session)
    assert streak["kind"] == "loss"
    assert streak["length"] == 2
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_pnl_service.py -v
```
Expected: import error / module not found.

- [ ] **Step 3: Implement `pnl_service.py`**

```python
# backend/app/services/pnl_service.py
"""Aggregate the Trade table into PnL summaries.

Backed by SQL queries over `Trade` rows (closed round-trips). All
timestamps are UTC; "today" = `[utc_midnight_today, utc_midnight_tomorrow)`.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Trade


def _utc_today_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


async def realized_pnl_today(session: AsyncSession) -> float:
    """Sum of net_profit on Trade rows whose exit_date falls today (UTC)."""
    start, end = _utc_today_window()
    result = await session.execute(
        select(func.coalesce(func.sum(Trade.net_profit), 0.0)).where(
            Trade.exit_date >= start, Trade.exit_date < end
        )
    )
    return float(result.scalar_one())


async def daily_summary(session: AsyncSession) -> dict[str, Any]:
    """Today-only stats: total PnL, trade count, win/loss split, last trade timestamp."""
    start, end = _utc_today_window()

    pnl_result = await session.execute(
        select(func.coalesce(func.sum(Trade.net_profit), 0.0)).where(
            Trade.exit_date >= start, Trade.exit_date < end
        )
    )
    total_pnl = float(pnl_result.scalar_one())

    trades_result = await session.execute(
        select(Trade)
        .where(Trade.exit_date >= start, Trade.exit_date < end)
        .order_by(desc(Trade.exit_date))
    )
    trades = list(trades_result.scalars().all())
    wins = sum(1 for t in trades if t.net_profit > 0)
    losses = sum(1 for t in trades if t.net_profit < 0)
    last_trade_at: Optional[datetime] = trades[0].exit_date if trades else None

    return {
        "realized_pnl_today": total_pnl,
        "trades_today": len(trades),
        "wins_today": wins,
        "losses_today": losses,
        "last_trade_at": last_trade_at,
    }


async def recent_streak(session: AsyncSession, *, lookback_limit: int = 50) -> dict[str, Any]:
    """Length and kind of the current win-or-loss streak across recent trades.

    Returns `{"kind": "win"|"loss"|"none", "length": int}`. A streak ends when
    a trade with the opposite sign appears. Zero-PnL trades break the streak.
    """
    result = await session.execute(
        select(Trade).order_by(desc(Trade.exit_date)).limit(max(1, min(lookback_limit, 200)))
    )
    trades = list(result.scalars().all())
    if not trades:
        return {"kind": "none", "length": 0}

    first_kind = "win" if trades[0].net_profit > 0 else "loss" if trades[0].net_profit < 0 else "none"
    if first_kind == "none":
        return {"kind": "none", "length": 0}

    length = 0
    for t in trades:
        kind = "win" if t.net_profit > 0 else "loss" if t.net_profit < 0 else "none"
        if kind != first_kind:
            break
        length += 1
    return {"kind": first_kind, "length": length}
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_pnl_service.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -q
```
Expected: **116 passed** (111 + 5).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pnl_service.py backend/tests/test_pnl_service.py
git commit -m "feat(pnl): daily PnL aggregator + win/loss streak from Trade table"
```

---

## Task 2: Wire PnL into snapshot providers

**Files:**
- Modify: `backend/strategy/runner.py`
- Modify: `backend/core/backtest/engine.py`

The P4 stub left `realized_pnl_today=0.0` in both snapshot providers. Now that `pnl_service.realized_pnl_today()` exists, plug it in so `MaxDailyLossPolicy` actually fires.

- [ ] **Step 1: Live snapshot uses pnl_service**

In `backend/strategy/runner.py`, modify `_live_portfolio_snapshot()` to open a DB session and read today's PnL:

```python
async def _live_portfolio_snapshot() -> PortfolioSnapshot:
    # Existing alpaca_service calls + pos_views construction unchanged.
    # ... existing code that builds pos_views, cash, equity ...

    realized_today = 0.0
    try:
        from app.database import AsyncSessionLocal
        from app.services import pnl_service

        async with AsyncSessionLocal() as session:
            realized_today = await pnl_service.realized_pnl_today(session)
    except Exception:
        # PnL lookup failure must not block trading — fall back to 0.
        realized_today = 0.0

    return PortfolioSnapshot(
        cash=cash,
        equity=equity,
        positions=pos_views,
        realized_pnl_today=realized_today,
    )
```

- [ ] **Step 2: Backtest snapshot uses portfolio.trades**

In `backend/core/backtest/engine.py`, modify `_build_snapshot_provider(portfolio, current_prices)` so the snapshot's `realized_pnl_today` reflects realized PnL within the simulation. Each closed `BacktestTradeRecord` with `side="sell"` represents a closed round-trip; the portfolio's `cash` already absorbed the proceeds. We compute realized-since-snapshot-start PnL by tracking opening notional vs closing notional:

```python
def _build_snapshot_provider(portfolio, current_prices):
    def _snapshot() -> PortfolioSnapshot:
        positions = {}
        for symbol, pos in portfolio.positions.items():
            price = current_prices.get(symbol, pos.average_entry_price)
            positions[symbol] = PortfolioPositionView(
                symbol=symbol,
                qty=pos.qty,
                average_entry_price=pos.average_entry_price,
                current_price=price,
                market_value=pos.qty * price,
                unrealized_pl=(price - pos.average_entry_price) * pos.qty,
            )

        # Realized PnL during this backtest run: simple FIFO across closed trades.
        realized = 0.0
        open_lots: dict[str, list[float]] = {}  # cost-basis stack per symbol
        for trade in portfolio.trades:
            if trade.side == "buy":
                open_lots.setdefault(trade.symbol, []).append(trade.notional)
            elif trade.side == "sell":
                cost = sum(open_lots.get(trade.symbol, []))
                realized += trade.notional - cost
                open_lots[trade.symbol] = []

        return PortfolioSnapshot(
            cash=portfolio.cash,
            equity=portfolio.equity(prices=current_prices),
            positions=positions,
            realized_pnl_today=realized,
        )
    return _snapshot
```

> Reasoning: backtest "today" is the entire simulation window (we don't track wall-clock days separately). Using cumulative realized PnL is the right thing for the daily-loss circuit breaker to behave consistently with the live runner over a multi-day backtest — the policy fires when cumulative loss exceeds the threshold.

- [ ] **Step 3: Run all tests**

```bash
pytest tests/ -q
```
Expected: **116 passed**. The existing engine integration test `test_engine_with_risk_guard_blocks_buy` should still pass; the engine test for toy strategy should still pass.

- [ ] **Step 4: Commit**

```bash
git add backend/strategy/runner.py backend/core/backtest/engine.py
git commit -m "feat(pnl): wire daily PnL into live + backtest snapshot providers"
```

---

## Task 3: Structured logging + correlation ID

**Files:**
- Create: `backend/core/observability/__init__.py`
- Create: `backend/core/observability/correlation.py`
- Create: `backend/core/observability/logging_setup.py`
- Create: `backend/app/middleware/__init__.py`
- Create: `backend/app/middleware/correlation.py`
- Create: `backend/tests/test_correlation.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_correlation.py
"""Correlation-ID context store + middleware."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.observability.correlation import (
    correlation_id_var,
    get_correlation_id,
    set_correlation_id,
)


def test_default_correlation_id_is_empty_string() -> None:
    # Each test starts with a fresh ContextVar token, so the default holds.
    assert get_correlation_id() == ""


def test_set_and_get() -> None:
    token = set_correlation_id("abc-123")
    try:
        assert get_correlation_id() == "abc-123"
    finally:
        correlation_id_var.reset(token)


def test_middleware_mints_uuid_when_no_header() -> None:
    from app.middleware.correlation import CorrelationIdMiddleware

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/echo")
    async def _echo() -> dict[str, str]:
        return {"id": get_correlation_id()}

    client = TestClient(app)
    response = client.get("/echo")
    payload = response.json()
    assert payload["id"]
    assert response.headers.get("X-Request-ID") == payload["id"]


def test_middleware_picks_up_inbound_request_id_header() -> None:
    from app.middleware.correlation import CorrelationIdMiddleware

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/echo")
    async def _echo() -> dict[str, str]:
        return {"id": get_correlation_id()}

    client = TestClient(app)
    response = client.get("/echo", headers={"X-Request-ID": "preset-id-42"})
    assert response.json()["id"] == "preset-id-42"
    assert response.headers["X-Request-ID"] == "preset-id-42"
```

- [ ] **Step 2: `correlation.py`**

```python
# backend/core/observability/correlation.py
"""ContextVar-backed correlation-id store.

Used by:
- HTTP middleware to attach a request ID to every log line emitted while
  the request is in flight.
- Logging filter (logging_setup.py) to inject the current id into JSON output.
- Strategy runner / backtest engine to scope their long-running operations.
"""
from __future__ import annotations

import contextvars

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def get_correlation_id() -> str:
    return correlation_id_var.get()


def set_correlation_id(value: str) -> contextvars.Token[str]:
    """Returns a Token. Pass to `correlation_id_var.reset(token)` to undo."""
    return correlation_id_var.set(value)
```

- [ ] **Step 3: `logging_setup.py`**

```python
# backend/core/observability/logging_setup.py
"""JSON-line logging configuration.

Each record becomes one JSON object on stdout with:
    timestamp, level, logger, message, correlation_id, plus any extras
    passed via `logger.info("...", extra={"key": value})`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from core.observability.correlation import get_correlation_id


_RESERVED_LOGRECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message",
}


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id() or None,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Attach any extras (anything on the record we didn't reserve).
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_KEYS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Replace the root handler with a JSON-line stdout handler."""
    root = logging.getLogger()
    root.setLevel(level)
    # Remove any pre-existing handlers (uvicorn injects its own, which we
    # want to keep distinct — uvicorn writes to stderr, our app handler to
    # stdout).
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLineFormatter())
    handler.setLevel(level)
    # Add but don't displace uvicorn's handler set during its own startup.
    if not any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, JsonLineFormatter) for h in root.handlers):
        root.addHandler(handler)
```

- [ ] **Step 4: `correlation.py` middleware**

```python
# backend/app/middleware/__init__.py
"""HTTP middlewares used by app.main."""
```

```python
# backend/app/middleware/correlation.py
"""Mints or reuses an X-Request-ID and stores it in the correlation-id ContextVar."""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from core.observability.correlation import correlation_id_var


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    HEADER_NAME = "X-Request-ID"

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(self.HEADER_NAME, "").strip()
        request_id = incoming or uuid.uuid4().hex
        token = correlation_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers[self.HEADER_NAME] = request_id
        return response
```

- [ ] **Step 5: Package `__init__.py`**

```python
# backend/core/observability/__init__.py
"""Observability primitives: correlation ID, structured logging, metrics."""
from __future__ import annotations

from core.observability.correlation import (
    correlation_id_var,
    get_correlation_id,
    set_correlation_id,
)
from core.observability.logging_setup import JsonLineFormatter, configure_logging

__all__ = [
    "JsonLineFormatter",
    "configure_logging",
    "correlation_id_var",
    "get_correlation_id",
    "set_correlation_id",
]
```

- [ ] **Step 6: Wire into `app/main.py`**

In `backend/app/main.py`:
1. Add import block near the top:
   ```python
   from core.observability import configure_logging
   from app.middleware.correlation import CorrelationIdMiddleware
   ```
2. Call `configure_logging()` once before `app = FastAPI(...)`.
3. After `app.add_middleware(CORSMiddleware, ...)`, add `app.add_middleware(CorrelationIdMiddleware)`.

- [ ] **Step 7: Run tests**

```bash
pytest tests/test_correlation.py -v
pytest tests/ -q
```
Expected: 4 PASS in correlation tests, **120 passed** total.

- [ ] **Step 8: Commit**

```bash
git add backend/core/observability/ backend/app/middleware/ backend/app/main.py backend/tests/test_correlation.py
git commit -m "feat(observability): structured logging + correlation-ID middleware"
```

---

## Task 4: Health endpoints

**Files:**
- Create: `backend/app/routers/health.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/models/observability.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_app_smoke.py`
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: API models**

```python
# backend/app/models/observability.py
"""Observability API models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: datetime
    version: str = "1.0.0"


class ReadinessCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class ReadinessResponse(BaseModel):
    ready: bool
    checks: list[ReadinessCheck] = Field(default_factory=list)


class StrategyHealthResponse(BaseModel):
    active_strategy_name: Optional[str] = None
    realized_pnl_today: float = 0.0
    trades_today: int = 0
    wins_today: int = 0
    losses_today: int = 0
    last_trade_at: Optional[datetime] = None
    streak_kind: str = "none"
    streak_length: int = 0
    open_position_count: int = 0
```

Update `app/models/__init__.py`: import and re-export `HealthResponse`, `ReadinessCheck`, `ReadinessResponse`, `StrategyHealthResponse`. Append to `__all__`.

- [ ] **Step 2: Health router**

```python
# backend/app/routers/health.py
"""Liveness + readiness probes."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import select

from app.dependencies import SessionDep
from app.database import StrategyProfile
from app.models import HealthResponse, ReadinessCheck, ReadinessResponse

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """Always 200 if the process can answer HTTP. Useful for k8s liveness."""
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(session: SessionDep) -> ReadinessResponse:
    """Probe DB + framework registry. Returns 200 with ready=false on partial degradation."""
    checks: list[ReadinessCheck] = []

    # DB ping.
    try:
        await session.execute(select(StrategyProfile).limit(1))
        checks.append(ReadinessCheck(name="database", ok=True))
    except Exception as exc:  # noqa: BLE001
        checks.append(ReadinessCheck(name="database", ok=False, detail=str(exc)))

    # Strategy registry resolves the default strategy.
    try:
        import strategies  # noqa: F401  -- decorators
        from core.strategy.registry import default_registry

        default_registry.get("strategy_b_v1")
        checks.append(ReadinessCheck(name="strategy_registry", ok=True))
    except Exception as exc:  # noqa: BLE001
        checks.append(ReadinessCheck(name="strategy_registry", ok=False, detail=str(exc)))

    return ReadinessResponse(ready=all(c.ok for c in checks), checks=checks)
```

- [ ] **Step 3: Register in `main.py`**

Add `from app.routers import health as health_router` and `app.include_router(health_router.router)` next to other router registrations.

- [ ] **Step 4: Smoke tests**

Append to `backend/tests/test_app_smoke.py`:

```python


def test_health_liveness(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


def test_health_readiness(client) -> None:
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert "ready" in body
    assert "checks" in body
    assert any(c["name"] == "database" for c in body["checks"])
```

- [ ] **Step 5: Update parity test**

Add to `EXPECTED_ROUTES`:
```python
("GET",    "/api/health"),
("GET",    "/api/health/ready"),
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/ -q
```
Expected: **122 passed** (120 + 2 smoke).

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/health.py backend/app/models/observability.py backend/app/models/__init__.py backend/app/main.py backend/tests/test_app_smoke.py backend/tests/test_openapi_parity.py
git commit -m "feat(observability): /api/health liveness + /api/health/ready readiness probes"
```

---

## Task 5: Metrics endpoint (Prometheus exposition format)

**Files:**
- Create: `backend/core/observability/metrics.py`
- Create: `backend/app/middleware/metrics.py`
- Create: `backend/app/routers/metrics.py`
- Create: `backend/tests/test_metrics.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_metrics.py
"""Metrics primitives + Prometheus rendering."""
from __future__ import annotations

import pytest

from core.observability.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    render_prometheus,
)


def test_counter_inc() -> None:
    c = Counter("http_requests_total", "HTTP requests served")
    assert c.value == 0
    c.inc()
    c.inc(2.5)
    assert c.value == 3.5


def test_gauge_set_and_inc() -> None:
    g = Gauge("active_websockets", "Open websocket count")
    g.set(5)
    g.inc(2)
    g.dec(1)
    assert g.value == 6


def test_histogram_buckets_and_count() -> None:
    h = Histogram("request_duration_seconds", "Request duration", buckets=[0.1, 0.5, 1.0])
    h.observe(0.05)  # falls in 0.1
    h.observe(0.3)   # falls in 0.5
    h.observe(0.8)   # falls in 1.0
    h.observe(2.0)   # +Inf
    assert h.count == 4
    assert pytest.approx(h.sum) == pytest.approx(0.05 + 0.3 + 0.8 + 2.0)
    assert h.bucket_counts[0.1] == 1
    assert h.bucket_counts[0.5] == 2
    assert h.bucket_counts[1.0] == 3


def test_render_prometheus_includes_help_and_type() -> None:
    registry = MetricsRegistry()
    counter = registry.counter("events_total", "Test events")
    counter.inc(7)
    output = render_prometheus(registry)
    assert "# HELP events_total Test events" in output
    assert "# TYPE events_total counter" in output
    assert "events_total 7.0" in output


def test_render_prometheus_histogram() -> None:
    registry = MetricsRegistry()
    h = registry.histogram("latency_seconds", "Latency", buckets=[0.1, 1.0])
    h.observe(0.05)
    h.observe(0.5)
    output = render_prometheus(registry)
    assert "# TYPE latency_seconds histogram" in output
    assert 'latency_seconds_bucket{le="0.1"} 1' in output
    assert 'latency_seconds_bucket{le="1.0"} 2' in output
    assert 'latency_seconds_bucket{le="+Inf"} 2' in output
    assert "latency_seconds_count 2" in output
```

- [ ] **Step 2: Implement `metrics.py`**

```python
# backend/core/observability/metrics.py
"""Hand-rolled Prometheus-compatible metrics primitives.

Stays dependency-free. The set of metric types here covers what Phase 5
needs: a global counter store, a small set of gauges, two latency
histograms. If we ever outgrow this, swap it for the official
`prometheus-client` package — the emitted exposition format already matches.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from threading import Lock
from typing import Iterable


@dataclass
class Counter:
    name: str
    help_text: str
    value: float = 0.0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def inc(self, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError("Counter cannot decrease.")
        with self._lock:
            self.value += amount


@dataclass
class Gauge:
    name: str
    help_text: str
    value: float = 0.0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def set(self, value: float) -> None:
        with self._lock:
            self.value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value -= amount


@dataclass
class Histogram:
    name: str
    help_text: str
    buckets: list[float]
    count: int = 0
    sum: float = 0.0
    bucket_counts: dict[float, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        # Ensure buckets are sorted and the +Inf bucket exists.
        self.buckets = sorted(self.buckets)
        for b in self.buckets:
            self.bucket_counts[b] = 0
        self.bucket_counts[math.inf] = 0

    def observe(self, value: float) -> None:
        with self._lock:
            self.count += 1
            self.sum += value
            for b in self.buckets:
                if value <= b:
                    self.bucket_counts[b] += 1
            self.bucket_counts[math.inf] += 1


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(self, name: str, help_text: str) -> Counter:
        if name not in self._counters:
            self._counters[name] = Counter(name=name, help_text=help_text)
        return self._counters[name]

    def gauge(self, name: str, help_text: str) -> Gauge:
        if name not in self._gauges:
            self._gauges[name] = Gauge(name=name, help_text=help_text)
        return self._gauges[name]

    def histogram(
        self,
        name: str,
        help_text: str,
        *,
        buckets: Iterable[float] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    ) -> Histogram:
        if name not in self._histograms:
            self._histograms[name] = Histogram(name=name, help_text=help_text, buckets=list(buckets))
        return self._histograms[name]

    def all(self) -> tuple[list[Counter], list[Gauge], list[Histogram]]:
        return (
            list(self._counters.values()),
            list(self._gauges.values()),
            list(self._histograms.values()),
        )


default_registry = MetricsRegistry()


def _format_bucket_le(value: float) -> str:
    return "+Inf" if value == math.inf else f"{value}"


def render_prometheus(registry: MetricsRegistry = default_registry) -> str:
    lines: list[str] = []
    counters, gauges, histograms = registry.all()

    for c in counters:
        lines.append(f"# HELP {c.name} {c.help_text}")
        lines.append(f"# TYPE {c.name} counter")
        lines.append(f"{c.name} {float(c.value)}")

    for g in gauges:
        lines.append(f"# HELP {g.name} {g.help_text}")
        lines.append(f"# TYPE {g.name} gauge")
        lines.append(f"{g.name} {float(g.value)}")

    for h in histograms:
        lines.append(f"# HELP {h.name} {h.help_text}")
        lines.append(f"# TYPE {h.name} histogram")
        for bucket, count in h.bucket_counts.items():
            le = _format_bucket_le(bucket)
            lines.append(f'{h.name}_bucket{{le="{le}"}} {int(count)}')
        lines.append(f"{h.name}_count {int(h.count)}")
        lines.append(f"{h.name}_sum {float(h.sum)}")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 3: HTTP request metrics middleware**

```python
# backend/app/middleware/metrics.py
"""ASGI middleware: count requests + record latency."""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from core.observability.metrics import default_registry


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._requests_total = default_registry.counter(
            "http_requests_total", "Total HTTP requests served"
        )
        self._latency = default_registry.histogram(
            "http_request_duration_seconds", "HTTP request duration in seconds"
        )

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            self._latency.observe(time.perf_counter() - start)
            self._requests_total.inc()
        return response
```

- [ ] **Step 4: `/metrics` router**

```python
# backend/app/routers/metrics.py
"""Prometheus metrics exposition endpoint.

Convention is to expose metrics at `/metrics` (NOT `/api/metrics`) so
generic Prometheus scrapers find it without prefix configuration.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from core.observability.metrics import render_prometheus

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def get_metrics() -> str:
    return render_prometheus()
```

- [ ] **Step 5: Wire into `main.py`**

1. Import: `from app.middleware.metrics import HttpMetricsMiddleware` and `from app.routers import metrics as metrics_router`.
2. After `CorrelationIdMiddleware`: `app.add_middleware(HttpMetricsMiddleware)`.
3. Register: `app.include_router(metrics_router.router)`.

- [ ] **Step 6: Smoke test**

Append to `tests/test_app_smoke.py`:

```python


def test_metrics_endpoint(client) -> None:
    # Hit a few endpoints first so counters have non-zero values.
    client.get("/api/health")
    client.get("/api/settings/status")

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text
```

- [ ] **Step 7: Update parity test**

Note: `/metrics` is registered with `include_in_schema=False` and is not under `/api/`. The existing parity test only enforces `/api/*` routes. If you want to lock `/metrics` too, add it to a separate inventory. For Phase 5 we leave it unlocked — the smoke test above is sufficient.

- [ ] **Step 8: Run tests**

```bash
pytest tests/test_metrics.py -v
pytest tests/ -q
```
Expected: 5 PASS metrics tests, **128 passed** total (122 + 5 + 1 smoke).

- [ ] **Step 9: Commit**

```bash
git add backend/core/observability/metrics.py backend/app/middleware/metrics.py backend/app/routers/metrics.py backend/app/main.py backend/tests/test_metrics.py backend/tests/test_app_smoke.py
git commit -m "feat(observability): /metrics endpoint with hand-rolled Prometheus exposition"
```

---

## Task 6: Notifications service (webhook)

**Files:**
- Create: `backend/app/services/notifications_service.py`
- Create: `backend/tests/test_notifications.py`
- Modify: `backend/app/services/risk_service.py`

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_notifications.py
"""Webhook notification delivery."""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.services import notifications_service


@pytest.mark.asyncio
async def test_dispatch_skips_when_no_webhook_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "")
    # Should not raise even though we never call out anywhere.
    await notifications_service.dispatch_risk_event(
        policy_name="symbol_blocklist",
        decision="deny",
        reason="GME on blocklist",
        symbol="GME",
        side="buy",
        notional=1000.0,
        qty=None,
    )


@pytest.mark.asyncio
async def test_dispatch_swallows_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "http://does-not-resolve.invalid")

    captured: dict[str, Any] = {}

    class _RaisingClient:
        def __init__(self, *args, **kwargs) -> None: pass
        async def __aenter__(self) -> "_RaisingClient": return self
        async def __aexit__(self, *args) -> None: return None
        async def post(self, url: str, **kwargs: Any):  # noqa: ANN401
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            raise RuntimeError("boom")

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", _RaisingClient)
    # Should not raise.
    await notifications_service.dispatch_risk_event(
        policy_name="symbol_blocklist",
        decision="deny",
        reason="GME on blocklist",
        symbol="GME",
        side="buy",
        notional=1000.0,
        qty=None,
    )
    assert captured["url"] == "http://does-not-resolve.invalid"
    assert captured["json"]["event"] == "risk_event"
    assert captured["json"]["policy_name"] == "symbol_blocklist"


@pytest.mark.asyncio
async def test_dispatch_sends_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "http://hooks.example/abc")

    captured: dict[str, Any] = {}

    class _RecordingClient:
        def __init__(self, *args, **kwargs) -> None: pass
        async def __aenter__(self) -> "_RecordingClient": return self
        async def __aexit__(self, *args) -> None: return None
        async def post(self, url: str, **kwargs: Any):
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            class _R:
                status_code = 200
                def raise_for_status(self) -> None: return None
            return _R()

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", _RecordingClient)
    await notifications_service.dispatch_risk_event(
        policy_name="max_daily_loss",
        decision="deny",
        reason="daily loss exceeded",
        symbol="AAPL",
        side="buy",
        notional=2_500.0,
        qty=None,
    )
    assert captured["url"] == "http://hooks.example/abc"
    payload = captured["json"]
    assert payload["event"] == "risk_event"
    assert payload["policy_name"] == "max_daily_loss"
    assert payload["symbol"] == "AAPL"
    assert payload["notional"] == 2_500.0
```

- [ ] **Step 2: Implement `notifications_service.py`**

```python
# backend/app/services/notifications_service.py
"""Webhook notification delivery.

Reads NOTIFICATIONS_WEBHOOK_URL from runtime_settings (which falls back to
the env var). Phase 5 supports a single generic webhook target — Slack,
Discord, and most monitoring systems accept a posted JSON body. Failure
to deliver is silently swallowed: notifications must never break trading.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from app import runtime_settings

logger = logging.getLogger(__name__)


def _webhook_url() -> str:
    return str(runtime_settings.get_setting("NOTIFICATIONS_WEBHOOK_URL", "") or "").strip()


async def dispatch_risk_event(
    *,
    policy_name: str,
    decision: str,
    reason: str,
    symbol: str,
    side: str,
    notional: Optional[float],
    qty: Optional[float],
) -> None:
    url = _webhook_url()
    if not url:
        return  # No webhook configured — silent skip.

    payload = {
        "event": "risk_event",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "policy_name": policy_name,
        "decision": decision,
        "reason": reason,
        "symbol": symbol,
        "side": side,
        "notional": notional,
        "qty": qty,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.5)) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except Exception:
        logger.exception("Notification webhook delivery failed for %s", policy_name)
```

- [ ] **Step 3: Hook into `risk_service.record_event`**

In `backend/app/services/risk_service.py`, after the existing `await session.commit()` at the end of `record_event`, fire-and-forget the webhook:

```python
async def record_event(
    session: AsyncSession,
    *,
    policy_name: str,
    decision: str,
    reason: str,
    symbol: str,
    side: str,
    notional: float | None,
    qty: float | None,
) -> None:
    session.add(
        RiskEvent(
            occurred_at=datetime.now(timezone.utc),
            policy_name=policy_name,
            decision=decision,
            reason=reason,
            symbol=symbol,
            side=side,
            notional=notional,
            qty=qty,
        )
    )
    await session.commit()

    # Fire-and-forget notification; never blocks the caller.
    try:
        from app.services import notifications_service

        await notifications_service.dispatch_risk_event(
            policy_name=policy_name,
            decision=decision,
            reason=reason,
            symbol=symbol,
            side=side,
            notional=notional,
            qty=qty,
        )
    except Exception:
        # Already silenced inside dispatch_risk_event, but defense in depth.
        pass
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_notifications.py -v
pytest tests/ -q
```
Expected: 3 PASS notifications, **131 passed** total.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/notifications_service.py backend/app/services/risk_service.py backend/tests/test_notifications.py
git commit -m "feat(notifications): webhook delivery hooked into risk events"
```

---

## Task 7: Strategy health aggregation endpoint

**Files:**
- Create: `backend/app/routers/strategy_health.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_app_smoke.py`
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: Router**

```python
# backend/app/routers/strategy_health.py
"""Aggregated strategy health: PnL today, trades today, streaks, open positions."""
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SessionDep, service_error
from app.models import StrategyHealthResponse
from app.services import alpaca_service, pnl_service, strategy_profiles_service

router = APIRouter(prefix="/api/strategy", tags=["strategy_health"])


@router.get("/health", response_model=StrategyHealthResponse)
async def get_strategy_health(session: SessionDep) -> StrategyHealthResponse:
    try:
        summary = await pnl_service.daily_summary(session)
        streak = await pnl_service.recent_streak(session)
    except Exception as exc:
        raise service_error(exc) from exc

    try:
        positions = await alpaca_service.list_positions()
    except Exception:
        positions = []

    try:
        active_name, _params = await strategy_profiles_service.get_active_strategy_execution_profile()
    except Exception:
        active_name = None

    return StrategyHealthResponse(
        active_strategy_name=active_name,
        realized_pnl_today=summary["realized_pnl_today"],
        trades_today=summary["trades_today"],
        wins_today=summary["wins_today"],
        losses_today=summary["losses_today"],
        last_trade_at=summary["last_trade_at"],
        streak_kind=streak["kind"],
        streak_length=streak["length"],
        open_position_count=len(positions),
    )
```

- [ ] **Step 2: Register router**

In `app/main.py`: `from app.routers import strategy_health as strategy_health_router` and `app.include_router(strategy_health_router.router)`.

- [ ] **Step 3: Smoke test**

Append to `tests/test_app_smoke.py`:

```python


def test_strategy_health_endpoint(client) -> None:
    response = client.get("/api/strategy/health")
    assert response.status_code == 200
    body = response.json()
    for field in (
        "active_strategy_name", "realized_pnl_today", "trades_today",
        "streak_kind", "streak_length", "open_position_count",
    ):
        assert field in body
```

- [ ] **Step 4: Update parity test**

Add to `EXPECTED_ROUTES`:
```python
("GET",    "/api/strategy/health"),
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/ -q
```
Expected: **132 passed** (131 + 1 smoke).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/strategy_health.py backend/app/main.py backend/tests/test_app_smoke.py backend/tests/test_openapi_parity.py
git commit -m "feat(api): GET /api/strategy/health aggregating PnL + streak + positions"
```

---

## Task 8: Final verification + push

- [ ] **Step 1: Full test sweep**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -v
```
Expected: **132 passed**, no `on_event` deprecation warnings.

- [ ] **Step 2: Live boot verification**

```bash
(uvicorn app.main:app --port 8765 > /tmp/uv.log 2>&1 &); sleep 3
echo "--- liveness ---"
curl -s http://127.0.0.1:8765/api/health; echo
echo "--- readiness ---"
curl -s http://127.0.0.1:8765/api/health/ready | head -c 400; echo
echo "--- strategy health ---"
curl -s http://127.0.0.1:8765/api/strategy/health | head -c 400; echo
echo "--- metrics ---"
curl -s http://127.0.0.1:8765/metrics | head -20
echo "--- correlation id is set ---"
curl -s -i http://127.0.0.1:8765/api/health | grep -i "x-request-id"
echo "--- preset correlation id ---"
curl -s -i -H "X-Request-ID: test-trace-1" http://127.0.0.1:8765/api/health | grep -i "x-request-id"
echo "--- existing endpoints ---"
for ep in /api/settings/status /api/strategies/registered /api/backtest/runs /api/risk/policies; do
  printf "%-30s -> " "$ep"
  curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765$ep"
done
pkill -f "uvicorn app.main:app --port 8765"; sleep 1
grep -E "ERROR|Exception" /tmp/uv.log | head -3
```
Expected:
- `/api/health` → `{"status":"ok",...}`.
- `/api/health/ready` → JSON with `ready` and `checks`.
- `/api/strategy/health` → JSON with `realized_pnl_today=0.0`, `trades_today=0` (no DB rows yet).
- `/metrics` → text starting with `# HELP http_requests_total ...`.
- `X-Request-ID` header present on every response, equals `test-trace-1` when supplied.
- All four pre-existing endpoints stay 200.
- No errors in log.

- [ ] **Step 3: Push**

```bash
git push -u origin feat/p5-observability
```

---

## Done-criteria

- All 7 tasks committed on `feat/p5-observability`, branched from `feat/p4-risk-layer`.
- `pytest tests/` green: **132 passed**.
- New packages: `core/observability/`, `app/middleware/`.
- New services: `pnl_service`, `notifications_service`.
- New routers: `health`, `metrics`, `strategy_health`.
- New routes added to parity: `/api/health`, `/api/health/ready`, `/api/strategy/health` (51 total). `/metrics` is unlocked (Prometheus convention, outside `/api/`).
- `MaxDailyLossPolicy` now sees real PnL data from the `Trade` table — daily-loss circuit breaker works end-to-end.
- Every HTTP response carries `X-Request-ID`; logs include `correlation_id`.
- Webhook delivery on risk events is wired (silent if `NOTIFICATIONS_WEBHOOK_URL` unset).

After Phase 5 lands, **the entire backend roadmap is complete** (P0 → P1 → P2 → P3 → P4 → P5). Frontend redesign is the next milestone — pick up the `/ui-designer` skill from where it left off.
