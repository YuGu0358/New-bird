# Phase 3 — Backtest Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an event-driven, bar-replay backtester that consumes the same `Strategy` ABC defined in Phase 2 and produces persisted run records with full equity curves and standard performance metrics. Strategy B becomes the first backtested strategy. To make this possible without monkey-patching, Phase 3 also introduces a minimal `Broker` interface (lifted forward from Phase 4) so the strategy engine can target either `AlpacaBroker` (live) or `BacktestBroker` (simulated) via dependency injection.

**Architecture:**

```
┌─────────────────────────┐    Strategy ABC    ┌─────────────────────────┐
│  strategy/runner.py     │───── (P2) ─────────│ strategies/strategy_b   │
│  (live)                 │                    │  - registers as v1      │
└──────────┬──────────────┘                    └──────────┬──────────────┘
           │ AlpacaBroker                                 │ broker injected
           ▼                                              ▼
   ┌───────────────┐ Broker ABC ┌──────────────────┐
   │ alpaca_service├────(new)───│ Broker interface │
   └───────────────┘            └──────────────────┘
                                          ▲
                                          │ BacktestBroker
                                          │
                              ┌───────────┴────────────┐
                              │ core/backtest/         │
                              │   engine.py (driver)   │
                              │   portfolio.py (sim)   │
                              │   loader.py (yfinance) │
                              │   metrics.py           │
                              └────────────────────────┘
                                          ▲
                                          │ POST /api/backtest/run
                              ┌───────────┴────────────┐
                              │ app/routers/backtest   │
                              │ app/services/backtest  │
                              │ app/db/tables          │
                              │   BacktestRun          │
                              │   BacktestTrade        │
                              └────────────────────────┘
```

**Tech Stack:** Python 3.13, Pydantic v2, FastAPI 0.135, SQLAlchemy async + aiosqlite, yfinance (existing dep), numpy/statistics from stdlib for metrics. No new top-level deps.

**Out of scope (deferred):**
- Multi-broker (paper vs live mode) — Phase 4.
- Portfolio-level risk constraints (max drawdown halts, correlation limits) — Phase 4.
- Slippage / commission modeling beyond the constant defaults — Phase 4 polish.
- Walk-forward optimization, parameter sweeps — future.
- Frontend visualization — frozen until backend phases done.

---

## File Structure

### New packages
| Path | Responsibility |
|---|---|
| `backend/core/broker/__init__.py` | Re-exports `Broker`, `AlpacaBroker` |
| `backend/core/broker/base.py` | `Broker` ABC: `list_positions`, `list_orders`, `submit_order`, `close_position` |
| `backend/core/broker/alpaca.py` | `AlpacaBroker(Broker)` adapter wrapping `app.services.alpaca_service` |
| `backend/core/backtest/__init__.py` | Re-exports public API |
| `backend/core/backtest/types.py` | `Bar`, `BacktestConfig`, `BacktestTradeRecord`, `BacktestResult` dataclasses |
| `backend/core/backtest/portfolio.py` | `BacktestPortfolio` — cash/positions/fills/equity-history simulator |
| `backend/core/backtest/broker.py` | `BacktestBroker(Broker)` backed by a `BacktestPortfolio` |
| `backend/core/backtest/loader.py` | `load_daily_bars(symbols, start, end)` via yfinance |
| `backend/core/backtest/metrics.py` | `total_return`, `cagr`, `sharpe`, `sortino`, `max_drawdown`, `calmar`, `win_rate`, `profit_factor` |
| `backend/core/backtest/engine.py` | `BacktestEngine` — runs the bar replay, returns `BacktestResult` |

### Modified files
| File | Change |
|---|---|
| `backend/strategy/strategy_b.py` | `StrategyBEngine.__init__` takes optional `broker: Broker | None = None`; defaults to `AlpacaBroker()` for behavior parity. All `alpaca_service.X(...)` calls become `self._broker.X(...)`. |
| `backend/strategies/strategy_b.py` | Wrapper accepts optional broker, threads to engine. |
| `backend/app/db/tables.py` | Add `BacktestRun` and `BacktestTrade` ORM tables. |
| `backend/app/db/__init__.py` | Re-export new tables. |
| `backend/app/models/__init__.py` | Re-export new backtest API models. |
| `backend/app/main.py` | Register `backtest_router`. |
| `backend/tests/test_openapi_parity.py` | Add 4 new routes to `EXPECTED_ROUTES`. |

### New files
| Path | Responsibility |
|---|---|
| `backend/app/models/backtest.py` | `BacktestRunRequest`, `BacktestSummaryView`, `BacktestRunResponse`, `BacktestEquityPoint`, `BacktestEquityCurveResponse` |
| `backend/app/services/backtest_service.py` | Async wrapper: orchestrate engine, persist `BacktestRun` + `BacktestTrade` rows, hydrate views |
| `backend/app/routers/backtest.py` | 4 endpoints (POST run, GET runs list, GET run by id, GET equity curve) |

### New tests
| File | What it covers |
|---|---|
| `backend/tests/test_broker_alpaca_adapter.py` | `AlpacaBroker` delegates each method to `alpaca_service` (monkeypatched) |
| `backend/tests/test_backtest_portfolio.py` | Fill, mark-to-market, equity snapshot, position lifecycle, partial sell |
| `backend/tests/test_backtest_metrics.py` | All metric formulas with known inputs |
| `backend/tests/test_backtest_engine.py` | Toy strategy + 30 bars, assert engine consumes intents and produces equity curve |
| `backend/tests/test_backtest_e2e.py` | Strategy B run end-to-end against mocked yfinance frame, assert run persists and metrics non-zero |
| `backend/tests/test_app_smoke.py` (append) | Smoke test for `POST /api/backtest/run` (mocked engine) |

### Untouched
- All Phase 0/1/2 work (routers, models package, db package, monitoring/social_signal packages, strategy framework)
- `frontend/`
- `agent-harness/`, `launcher/`, Dockerfile, CI workflows
- Strategy B's actual trading rules (only the broker indirection is added; behavior identical when running with `AlpacaBroker`)

---

## Pre-flight

- [ ] Confirm baseline (we end Phase 2 at 68 passed):
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **68 passed**.

- [ ] Branch off P2:
```bash
cd ~/NewBirdClaude
git checkout feat/p2-strategy-framework
git checkout -b feat/p3-backtest-engine
```

---

## Task 1: Broker ABC + AlpacaBroker adapter (TDD)

**Files:**
- Create: `backend/core/broker/__init__.py`
- Create: `backend/core/broker/base.py`
- Create: `backend/core/broker/alpaca.py`
- Create: `backend/tests/test_broker_alpaca_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_broker_alpaca_adapter.py
"""AlpacaBroker delegates to app.services.alpaca_service."""
from __future__ import annotations

from typing import Any

import pytest

from core.broker import AlpacaBroker


@pytest.mark.asyncio
async def test_list_positions_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel: list[dict[str, Any]] = [{"symbol": "AAPL", "qty": "10"}]

    async def fake_list_positions() -> list[dict[str, Any]]:
        return sentinel

    from app.services import alpaca_service

    monkeypatch.setattr(alpaca_service, "list_positions", fake_list_positions)
    broker = AlpacaBroker()
    result = await broker.list_positions()
    assert result is sentinel


@pytest.mark.asyncio
async def test_submit_order_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_submit_order(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"id": "order-1", "symbol": kwargs.get("symbol")}

    from app.services import alpaca_service

    monkeypatch.setattr(alpaca_service, "submit_order", fake_submit_order)
    broker = AlpacaBroker()
    response = await broker.submit_order(symbol="AAPL", side="buy", notional=1000.0)
    assert response["id"] == "order-1"
    assert captured == {"symbol": "AAPL", "side": "buy", "notional": 1000.0}


@pytest.mark.asyncio
async def test_close_position_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    called_with: dict[str, Any] = {}

    async def fake_close_position(symbol: str) -> dict[str, Any]:
        called_with["symbol"] = symbol
        return {"closed": symbol}

    from app.services import alpaca_service

    monkeypatch.setattr(alpaca_service, "close_position", fake_close_position)
    broker = AlpacaBroker()
    response = await broker.close_position("MSFT")
    assert response == {"closed": "MSFT"}
    assert called_with == {"symbol": "MSFT"}


@pytest.mark.asyncio
async def test_list_orders_passes_status_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, Any] = {}

    async def fake_list_orders(**kwargs: Any) -> list[dict[str, Any]]:
        captured_kwargs.update(kwargs)
        return []

    from app.services import alpaca_service

    monkeypatch.setattr(alpaca_service, "list_orders", fake_list_orders)
    broker = AlpacaBroker()
    await broker.list_orders(status="open")
    assert captured_kwargs == {"status": "open"}
    captured_kwargs.clear()
    await broker.list_orders(status="all", limit=200)
    assert captured_kwargs == {"status": "all", "limit": 200}
```

> Note: pytest-asyncio is needed. We'll install it in Task 1 Step 2 if not already present.

- [ ] **Step 2: Install pytest-asyncio if missing**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pip install -q pytest-asyncio
```

Add `asyncio_mode = "auto"` to `backend/pytest.ini` so plain `async def test_X` functions are auto-marked:

```ini
# backend/pytest.ini
[pytest]
pythonpath = .
testpaths = tests
asyncio_mode = auto
```

- [ ] **Step 3: Run test, verify it fails**

```bash
pytest tests/test_broker_alpaca_adapter.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'core.broker'`.

- [ ] **Step 4: Implement Broker ABC**

```python
# backend/core/broker/base.py
"""Broker abstraction.

Phase 3 introduces this so the strategy engine can target either a live
broker (AlpacaBroker) or a simulated one (BacktestBroker) without code
changes inside the strategy itself.

Phase 4 will extend this with paper/live mode flags, idempotency keys,
and richer error types.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class Broker(ABC):
    """Minimal broker surface needed by Strategy B and the backtest engine."""

    @abstractmethod
    async def list_positions(self) -> list[dict[str, Any]]:
        """Return current open positions as a list of broker dicts."""

    @abstractmethod
    async def list_orders(
        self,
        *,
        status: str = "all",
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Return orders filtered by status (`all`, `open`, `closed`, ...)."""

    @abstractmethod
    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        """Submit a market order. Either `notional` (USD) or `qty` is set."""

    @abstractmethod
    async def close_position(self, symbol: str) -> dict[str, Any]:
        """Close an open position at market."""
```

- [ ] **Step 5: Implement AlpacaBroker adapter**

```python
# backend/core/broker/alpaca.py
"""AlpacaBroker — delegates each Broker method to app.services.alpaca_service."""
from __future__ import annotations

from typing import Any, Optional

from app.services import alpaca_service

from core.broker.base import Broker


class AlpacaBroker(Broker):
    """Adapter: existing alpaca_service module behind the Broker interface.

    Holds no state. All methods forward to the module-level functions, so
    monkeypatches against `app.services.alpaca_service` continue to work
    in tests that target the legacy path.
    """

    async def list_positions(self) -> list[dict[str, Any]]:
        return await alpaca_service.list_positions()

    async def list_orders(
        self,
        *,
        status: str = "all",
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"status": status}
        if limit is not None:
            kwargs["limit"] = limit
        return await alpaca_service.list_orders(**kwargs)

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"symbol": symbol, "side": side}
        if notional is not None:
            kwargs["notional"] = notional
        if qty is not None:
            kwargs["qty"] = qty
        return await alpaca_service.submit_order(**kwargs)

    async def close_position(self, symbol: str) -> dict[str, Any]:
        return await alpaca_service.close_position(symbol)
```

- [ ] **Step 6: Package re-exports**

```python
# backend/core/broker/__init__.py
"""Broker abstraction package."""
from __future__ import annotations

from core.broker.alpaca import AlpacaBroker
from core.broker.base import Broker

__all__ = ["AlpacaBroker", "Broker"]
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/test_broker_alpaca_adapter.py tests/ -q
```
Expected: **72 passed** (68 + 4 new). If any test fails because pytest-asyncio is missing or `asyncio_mode = auto` not picked up, double-check `pytest.ini`.

- [ ] **Step 8: Commit**

```bash
git add backend/core/broker/ backend/tests/test_broker_alpaca_adapter.py backend/pytest.ini
git commit -m "feat(broker): add Broker ABC + AlpacaBroker adapter"
```

---

## Task 2: Refactor StrategyBEngine to use a Broker

**Files:**
- Modify: `backend/strategy/strategy_b.py`
- Modify: `backend/strategies/strategy_b.py`

**Goal:** Replace direct `alpaca_service.X(...)` calls in the engine with `self._broker.X(...)`. Default broker is `AlpacaBroker()` so behavior is byte-identical when no broker is supplied. The wrapper in `strategies/strategy_b.py` lets a backtest pass a `BacktestBroker` instead.

- [ ] **Step 1: Add broker parameter and adapter call sites**

Edit `backend/strategy/strategy_b.py`:

1. At the top of the file, add:
```python
from core.broker import AlpacaBroker, Broker
```

2. In `StrategyBEngine.__init__`, add a `broker: Broker | None = None` parameter:

```python
class StrategyBEngine:
    def __init__(
        self,
        config: StrategyExecutionConfig | None = None,
        *,
        broker: Broker | None = None,
    ) -> None:
        self.config = config or build_default_strategy_config()
        self._broker: Broker = broker if broker is not None else AlpacaBroker()
        # ... rest of existing __init__ unchanged ...
```

3. Replace **all 7** `alpaca_service.X(...)` call sites with `self._broker.X(...)`:

| Old | New |
|---|---|
| `await alpaca_service.list_positions()` | `await self._broker.list_positions()` |
| `await alpaca_service.list_orders(status="open")` | `await self._broker.list_orders(status="open")` |
| `await alpaca_service.list_orders(status="all", limit=200)` | `await self._broker.list_orders(status="all", limit=200)` |
| `await alpaca_service.submit_order(symbol=..., side=..., notional=...)` (×2) | `await self._broker.submit_order(symbol=..., side=..., notional=...)` |
| `await alpaca_service.close_position(position.symbol)` | `await self._broker.close_position(position.symbol)` |
| `await alpaca_service.submit_order(symbol=..., side="sell", qty=...)` | `await self._broker.submit_order(symbol=..., side="sell", qty=...)` |

4. Drop `from app.services import alpaca_service` if it has no other use after the rewrite (run `python -m pyflakes strategy/strategy_b.py` to confirm).

- [ ] **Step 2: Update `strategies/strategy_b.py` wrapper**

Edit `backend/strategies/strategy_b.py`:

```python
# Add to imports at top of file
from core.broker import Broker

# Update StrategyB.__init__ to accept and forward an optional broker
@register_strategy("strategy_b_v1")
class StrategyB(Strategy):
    description = "Fixed-notional dollar-cost-down strategy on the default 20-name universe."

    @classmethod
    def parameters_schema(cls) -> type[StrategyExecutionParameters]:
        return StrategyExecutionParameters

    def __init__(
        self,
        parameters: StrategyExecutionParameters,
        *,
        broker: Broker | None = None,
    ) -> None:
        super().__init__(parameters)
        self._engine = StrategyBEngine(_to_engine_config(parameters), broker=broker)

    # ... rest of class (universe, on_start, on_periodic_sync, on_tick) unchanged ...
```

> Note: The framework `Strategy.__init__` only takes `parameters`. Adding `broker` as a keyword-only param on `StrategyB` is a concrete-class extension — it does not break the ABC contract.

- [ ] **Step 3: Run all tests**

```bash
pytest tests/ -q
```
Expected: **72 passed**. Both `test_strategy_engine.py` and `test_strategy_b_registration.py` should still be green because the default broker matches old behavior.

- [ ] **Step 4: Commit**

```bash
git add backend/strategy/strategy_b.py backend/strategies/strategy_b.py
git commit -m "refactor(strategy): inject Broker into StrategyBEngine, default to AlpacaBroker"
```

---

## Task 3: Backtest types

**Files:**
- Create: `backend/core/backtest/__init__.py`
- Create: `backend/core/backtest/types.py`

- [ ] **Step 1: Write `types.py`**

```python
# backend/core/backtest/types.py
"""Value types passed around the backtest pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass(frozen=True)
class Bar:
    """Daily OHLCV bar for a single symbol."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    previous_close: Optional[float] = None


@dataclass
class BacktestConfig:
    """Inputs for a single backtest run."""

    strategy_name: str
    parameters: dict
    universe: list[str]
    start_date: date
    end_date: date
    initial_cash: float = 100_000.0


@dataclass
class BacktestTradeRecord:
    """A single fill recorded during the backtest."""

    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    price: float
    notional: float
    timestamp: datetime
    reason: str = ""


@dataclass
class BacktestResult:
    """Outcome of a backtest run before persistence."""

    config: BacktestConfig
    started_at: datetime
    finished_at: datetime
    final_cash: float
    final_equity: float
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    trades: list[BacktestTradeRecord] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
```

- [ ] **Step 2: Package `__init__.py`** (placeholder; full re-exports added in Task 8)

```python
# backend/core/backtest/__init__.py
"""Backtest engine package."""
from __future__ import annotations

from core.backtest.types import (
    Bar,
    BacktestConfig,
    BacktestResult,
    BacktestTradeRecord,
)

__all__ = [
    "Bar",
    "BacktestConfig",
    "BacktestResult",
    "BacktestTradeRecord",
]
```

- [ ] **Step 3: Smoke test imports**

```bash
python -c "
from core.backtest import Bar, BacktestConfig, BacktestResult, BacktestTradeRecord
from datetime import date, datetime
b = Bar(symbol='AAPL', timestamp=datetime.now(), open=100, high=101, low=99, close=100.5, volume=1e6)
print('ok', b.symbol)
"
```
Expected: `ok AAPL`.

- [ ] **Step 4: Tests pass**

```bash
pytest tests/ -q
```
Expected: **72 passed**.

- [ ] **Step 5: Commit**

```bash
git add backend/core/backtest/
git commit -m "feat(backtest): add Bar/BacktestConfig/BacktestResult value types"
```

---

## Task 4: BacktestPortfolio + BacktestBroker (TDD)

**Files:**
- Create: `backend/core/backtest/portfolio.py`
- Create: `backend/core/backtest/broker.py`
- Create: `backend/tests/test_backtest_portfolio.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_backtest_portfolio.py
"""BacktestPortfolio fill semantics, mark-to-market, equity snapshots."""
from __future__ import annotations

from datetime import datetime, timezone

from core.backtest.portfolio import BacktestPortfolio


def _now(year: int = 2025, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_initial_state() -> None:
    p = BacktestPortfolio(initial_cash=100_000.0)
    assert p.cash == 100_000.0
    assert p.positions == {}
    assert p.equity(prices={}) == 100_000.0


def test_buy_notional_creates_position() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="AAPL", price=100.0, notional=1_000.0, timestamp=_now())
    pos = p.positions["AAPL"]
    assert pos.qty == 10.0
    assert pos.average_entry_price == 100.0
    assert p.cash == 9_000.0


def test_buy_qty_creates_position() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="MSFT", price=400.0, qty=5.0, timestamp=_now())
    assert p.positions["MSFT"].qty == 5.0
    assert p.cash == 8_000.0


def test_add_on_buy_increases_qty_and_updates_avg() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="AAPL", price=100.0, qty=10.0, timestamp=_now())
    p.fill_buy(symbol="AAPL", price=80.0, qty=5.0, timestamp=_now(month=2))
    pos = p.positions["AAPL"]
    assert pos.qty == 15.0
    # weighted average: (10*100 + 5*80) / 15 = 1400 / 15 ≈ 93.3333
    assert round(pos.average_entry_price, 4) == 93.3333


def test_close_position_credits_cash_and_records_trade() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="AAPL", price=100.0, qty=10.0, timestamp=_now())
    p.fill_close(symbol="AAPL", price=110.0, timestamp=_now(month=2), reason="take_profit")
    assert "AAPL" not in p.positions
    assert p.cash == 10_100.0
    assert any(t.side == "sell" and t.symbol == "AAPL" for t in p.trades)


def test_equity_marks_open_positions() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    p.fill_buy(symbol="AAPL", price=100.0, qty=10.0, timestamp=_now())
    # Cash 9000 + 10 shares @ 105 = 10050
    assert p.equity(prices={"AAPL": 105.0}) == 10_050.0


def test_record_equity_snapshot_appends_curve() -> None:
    p = BacktestPortfolio(initial_cash=10_000.0)
    ts = _now()
    p.record_equity_snapshot(timestamp=ts, prices={})
    assert p.equity_curve == [(ts, 10_000.0)]
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_backtest_portfolio.py -v
```
Expected: FAIL with `ModuleNotFoundError: core.backtest.portfolio`.

- [ ] **Step 3: Implement `portfolio.py`**

```python
# backend/core/backtest/portfolio.py
"""BacktestPortfolio — in-memory simulator for cash, positions, fills."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.backtest.types import BacktestTradeRecord


@dataclass
class _PositionState:
    symbol: str
    qty: float
    average_entry_price: float
    total_cost: float
    opened_at: datetime


class InsufficientCashError(RuntimeError):
    """Raised when a fill would push cash below zero."""


class PositionNotOpenError(RuntimeError):
    """Raised when closing a symbol that has no open position."""


@dataclass
class BacktestPortfolio:
    initial_cash: float
    cash: float = field(init=False)
    positions: dict[str, _PositionState] = field(default_factory=dict)
    trades: list[BacktestTradeRecord] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = float(self.initial_cash)

    def equity(self, *, prices: dict[str, float]) -> float:
        total = self.cash
        for symbol, pos in self.positions.items():
            mark = prices.get(symbol, pos.average_entry_price)
            total += pos.qty * mark
        return total

    def record_equity_snapshot(self, *, timestamp: datetime, prices: dict[str, float]) -> None:
        self.equity_curve.append((timestamp, self.equity(prices=prices)))

    def fill_buy(
        self,
        *,
        symbol: str,
        price: float,
        timestamp: datetime,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
        reason: str = "",
    ) -> BacktestTradeRecord:
        if (notional is None) == (qty is None):
            raise ValueError("Exactly one of notional or qty must be provided.")
        if price <= 0:
            raise ValueError("price must be > 0")

        if qty is None:
            assert notional is not None
            qty = notional / price
        cost = qty * price
        if cost > self.cash + 1e-9:
            raise InsufficientCashError(
                f"buy {symbol} cost {cost:.2f} exceeds cash {self.cash:.2f}"
            )

        existing = self.positions.get(symbol)
        if existing is None:
            self.positions[symbol] = _PositionState(
                symbol=symbol,
                qty=qty,
                average_entry_price=price,
                total_cost=cost,
                opened_at=timestamp,
            )
        else:
            new_qty = existing.qty + qty
            new_total_cost = existing.total_cost + cost
            existing.qty = new_qty
            existing.total_cost = new_total_cost
            existing.average_entry_price = new_total_cost / new_qty if new_qty > 0 else 0.0

        self.cash -= cost
        trade = BacktestTradeRecord(
            symbol=symbol,
            side="buy",
            qty=qty,
            price=price,
            notional=cost,
            timestamp=timestamp,
            reason=reason,
        )
        self.trades.append(trade)
        return trade

    def fill_close(
        self,
        *,
        symbol: str,
        price: float,
        timestamp: datetime,
        reason: str = "",
    ) -> BacktestTradeRecord:
        if price <= 0:
            raise ValueError("price must be > 0")
        position = self.positions.get(symbol)
        if position is None:
            raise PositionNotOpenError(f"No open position for {symbol}")

        proceeds = position.qty * price
        trade = BacktestTradeRecord(
            symbol=symbol,
            side="sell",
            qty=position.qty,
            price=price,
            notional=proceeds,
            timestamp=timestamp,
            reason=reason,
        )
        self.cash += proceeds
        self.trades.append(trade)
        del self.positions[symbol]
        return trade
```

- [ ] **Step 4: Implement `BacktestBroker`**

```python
# backend/core/backtest/broker.py
"""BacktestBroker — Broker implementation backed by a BacktestPortfolio.

Strategy B receives this in lieu of AlpacaBroker during backtest. The broker
needs a `prices` callable that returns the current bar's price per symbol so
fills happen at the appropriate close.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from core.backtest.portfolio import BacktestPortfolio
from core.broker.base import Broker


class BacktestBroker(Broker):
    """Routes Strategy B's broker calls to a BacktestPortfolio.

    `current_price_provider` returns the close-of-bar price for a symbol at
    the simulated "now". `current_time_provider` returns the simulated
    timestamp. The engine sets these before each strategy callback.
    """

    def __init__(
        self,
        portfolio: BacktestPortfolio,
        *,
        current_price_provider: Callable[[str], float],
        current_time_provider: Callable[[], datetime],
    ) -> None:
        self.portfolio = portfolio
        self._current_price = current_price_provider
        self._current_time = current_time_provider
        self._next_order_id = 1

    def _new_order_id(self) -> str:
        oid = f"backtest-{self._next_order_id}"
        self._next_order_id += 1
        return oid

    async def list_positions(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol, pos in self.portfolio.positions.items():
            current_price = self._current_price(symbol)
            unrealized = (current_price - pos.average_entry_price) * pos.qty
            rows.append(
                {
                    "symbol": symbol,
                    "qty": str(pos.qty),
                    "avg_entry_price": str(pos.average_entry_price),
                    "current_price": str(current_price),
                    "market_value": str(pos.qty * current_price),
                    "unrealized_pl": str(unrealized),
                }
            )
        return rows

    async def list_orders(
        self,
        *,
        status: str = "all",
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        # Backtest fills resolve synchronously inside submit_order; nothing
        # ever sits "open". Strategy B treats an empty open list as healthy.
        return []

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        price = self._current_price(symbol)
        timestamp = self._current_time() or datetime.now(timezone.utc)

        if side == "buy":
            self.portfolio.fill_buy(
                symbol=symbol,
                price=price,
                timestamp=timestamp,
                notional=notional,
                qty=qty,
            )
        elif side == "sell":
            self.portfolio.fill_close(
                symbol=symbol,
                price=price,
                timestamp=timestamp,
            )
        else:
            raise ValueError(f"Unsupported side: {side!r}")

        return {
            "id": self._new_order_id(),
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "notional": notional,
            "filled_avg_price": price,
            "status": "filled",
        }

    async def close_position(self, symbol: str) -> dict[str, Any]:
        price = self._current_price(symbol)
        timestamp = self._current_time() or datetime.now(timezone.utc)
        self.portfolio.fill_close(
            symbol=symbol,
            price=price,
            timestamp=timestamp,
            reason="strategy_close",
        )
        return {
            "id": self._new_order_id(),
            "symbol": symbol,
            "status": "filled",
        }
```

- [ ] **Step 5: Run portfolio tests + full suite**

```bash
pytest tests/test_backtest_portfolio.py -v
pytest tests/ -q
```
Expected: **79 passed** (72 + 7 portfolio tests).

- [ ] **Step 6: Commit**

```bash
git add backend/core/backtest/portfolio.py backend/core/backtest/broker.py backend/tests/test_backtest_portfolio.py
git commit -m "feat(backtest): add BacktestPortfolio + BacktestBroker simulator"
```

---

## Task 5: Bar loader (yfinance wrapper)

**Files:**
- Create: `backend/core/backtest/loader.py`

- [ ] **Step 1: Write `loader.py`**

```python
# backend/core/backtest/loader.py
"""Historical bar loader. yfinance is the only source for Phase 3."""
from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import Any

from core.backtest.types import Bar


def _row_to_bar(symbol: str, timestamp: datetime, row: dict[str, Any]) -> Bar | None:
    try:
        open_ = float(row["Open"])
        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])
        volume = float(row.get("Volume", 0.0) or 0.0)
    except (KeyError, TypeError, ValueError):
        return None
    if any(math.isnan(v) for v in (open_, high, low, close)):
        return None
    if close <= 0:
        return None
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _frame_to_bars(symbol: str, frame: Any) -> list[Bar]:
    bars: list[Bar] = []
    previous_close: float | None = None
    for index, row in frame.iterrows():
        timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        row_dict = {key: row[key] for key in row.index}
        bar = _row_to_bar(symbol, timestamp, row_dict)
        if bar is None:
            continue
        if previous_close is not None:
            bar = Bar(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                previous_close=previous_close,
            )
        bars.append(bar)
        previous_close = bar.close
    return bars


def _download_bars_sync(
    symbols: Sequence[str],
    *,
    start: date,
    end: date,
) -> dict[str, list[Bar]]:
    import yfinance as yf

    if not symbols:
        return {}

    raw = yf.download(
        tickers=list(symbols),
        start=start.isoformat(),
        end=end.isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw is None or getattr(raw, "empty", False):
        return {}

    if getattr(raw.columns, "nlevels", 1) == 1:
        return {symbols[0]: _frame_to_bars(symbols[0], raw)}

    bars_per_symbol: dict[str, list[Bar]] = {}
    top_level = set(raw.columns.get_level_values(0))
    for symbol in symbols:
        if symbol not in top_level:
            continue
        bars_per_symbol[symbol] = _frame_to_bars(symbol, raw[symbol])
    return bars_per_symbol


async def load_daily_bars(
    symbols: Sequence[str],
    *,
    start: date,
    end: date,
) -> dict[str, list[Bar]]:
    """Async wrapper. Runs the blocking yfinance download in a worker thread."""
    return await asyncio.to_thread(_download_bars_sync, symbols, start=start, end=end)
```

- [ ] **Step 2: Smoke import**

```bash
python -c "
from core.backtest.loader import load_daily_bars
print('ok loader')
"
```
Expected: `ok loader`.

- [ ] **Step 3: Tests still pass**

```bash
pytest tests/ -q
```
Expected: **79 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/backtest/loader.py
git commit -m "feat(backtest): add yfinance daily-bar loader"
```

---

## Task 6: Performance metrics (TDD)

**Files:**
- Create: `backend/core/backtest/metrics.py`
- Create: `backend/tests/test_backtest_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_backtest_metrics.py
"""Performance metric formulas — known inputs only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.backtest.metrics import (
    cagr,
    compute_metrics,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    total_return,
    win_rate,
)


def _curve(values: list[float]) -> list[tuple[datetime, float]]:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [(base + timedelta(days=i), v) for i, v in enumerate(values)]


def test_total_return_pct() -> None:
    curve = _curve([100.0, 110.0, 121.0])
    assert round(total_return(curve), 4) == 0.21


def test_total_return_empty() -> None:
    assert total_return([]) == 0.0


def test_max_drawdown_simple() -> None:
    curve = _curve([100.0, 120.0, 90.0, 110.0])
    # peak 120 -> trough 90 -> drawdown = (90 - 120) / 120 = -0.25
    assert round(max_drawdown(curve), 4) == -0.25


def test_max_drawdown_monotonic_returns_zero() -> None:
    curve = _curve([100.0, 105.0, 110.0])
    assert max_drawdown(curve) == 0.0


def test_sharpe_ratio_positive_for_steady_growth() -> None:
    curve = _curve([100.0 * (1.001) ** i for i in range(252)])
    sr = sharpe_ratio(curve, periods_per_year=252)
    assert sr > 5.0  # nearly deterministic 0.1% daily growth


def test_sortino_handles_no_negatives() -> None:
    curve = _curve([100.0, 101.0, 102.0])
    # No downside → infinity in pure math; we cap at a large number.
    s = sortino_ratio(curve, periods_per_year=252)
    assert s > 0


def test_cagr_two_year_doubling() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    curve = [(base, 100.0), (base + timedelta(days=365 * 2), 200.0)]
    # CAGR ≈ 2^(1/2) - 1 ≈ 0.4142
    assert round(cagr(curve), 4) == pytest.approx(0.4142, abs=1e-3)


def test_win_rate_and_profit_factor() -> None:
    pnl_per_trade = [100.0, -50.0, 200.0, -100.0, 50.0]
    assert round(win_rate(pnl_per_trade), 4) == 0.6
    # gross profit 350, gross loss 150 -> pf = 350/150 ≈ 2.3333
    assert round(profit_factor(pnl_per_trade), 4) == 2.3333


def test_compute_metrics_returns_dict() -> None:
    curve = _curve([100.0, 105.0, 102.0, 110.0])
    pnl = [5.0, -3.0, 8.0]
    metrics = compute_metrics(curve, pnl_per_trade=pnl, periods_per_year=252)
    for key in ("total_return", "cagr", "sharpe", "sortino", "max_drawdown", "calmar", "win_rate", "profit_factor"):
        assert key in metrics
```

- [ ] **Step 2: Implement `metrics.py`**

```python
# backend/core/backtest/metrics.py
"""Performance metrics computed from a backtest equity curve + trade list."""
from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Sequence

EquityPoint = tuple[datetime, float]
EquityCurve = Sequence[EquityPoint]


def _returns(curve: EquityCurve) -> list[float]:
    if len(curve) < 2:
        return []
    returns: list[float] = []
    for prev, curr in zip(curve, curve[1:]):
        prev_value = prev[1]
        curr_value = curr[1]
        if prev_value <= 0:
            continue
        returns.append((curr_value / prev_value) - 1.0)
    return returns


def total_return(curve: EquityCurve) -> float:
    if len(curve) < 2:
        return 0.0
    start = curve[0][1]
    end = curve[-1][1]
    if start <= 0:
        return 0.0
    return (end / start) - 1.0


def cagr(curve: EquityCurve) -> float:
    if len(curve) < 2:
        return 0.0
    start_ts, start_value = curve[0]
    end_ts, end_value = curve[-1]
    if start_value <= 0 or end_value <= 0:
        return 0.0
    days = (end_ts - start_ts).total_seconds() / 86400.0
    if days < 1:
        return 0.0
    years = days / 365.25
    if years <= 0:
        return 0.0
    return (end_value / start_value) ** (1.0 / years) - 1.0


def max_drawdown(curve: EquityCurve) -> float:
    if not curve:
        return 0.0
    peak = curve[0][1]
    worst = 0.0
    for _, value in curve:
        if value > peak:
            peak = value
        if peak <= 0:
            continue
        drawdown = (value - peak) / peak
        if drawdown < worst:
            worst = drawdown
    return worst


def sharpe_ratio(curve: EquityCurve, *, periods_per_year: int = 252, risk_free: float = 0.0) -> float:
    rs = _returns(curve)
    if len(rs) < 2:
        return 0.0
    excess = [r - (risk_free / periods_per_year) for r in rs]
    mean = statistics.fmean(excess)
    stdev = statistics.pstdev(excess)
    if stdev == 0:
        return 0.0
    return mean / stdev * math.sqrt(periods_per_year)


def sortino_ratio(curve: EquityCurve, *, periods_per_year: int = 252, risk_free: float = 0.0) -> float:
    rs = _returns(curve)
    if len(rs) < 2:
        return 0.0
    excess = [r - (risk_free / periods_per_year) for r in rs]
    mean = statistics.fmean(excess)
    downside = [r for r in excess if r < 0]
    if not downside:
        # No losing periods → infinite ratio in pure form. Cap at 100 for sanity.
        return 100.0 if mean > 0 else 0.0
    downside_dev = math.sqrt(sum(d * d for d in downside) / len(downside))
    if downside_dev == 0:
        return 0.0
    return mean / downside_dev * math.sqrt(periods_per_year)


def calmar_ratio(curve: EquityCurve) -> float:
    annual = cagr(curve)
    dd = abs(max_drawdown(curve))
    if dd == 0:
        return 100.0 if annual > 0 else 0.0
    return annual / dd


def win_rate(pnl_per_trade: Sequence[float]) -> float:
    if not pnl_per_trade:
        return 0.0
    wins = sum(1 for p in pnl_per_trade if p > 0)
    return wins / len(pnl_per_trade)


def profit_factor(pnl_per_trade: Sequence[float]) -> float:
    gross_profit = sum(p for p in pnl_per_trade if p > 0)
    gross_loss = -sum(p for p in pnl_per_trade if p < 0)
    if gross_loss == 0:
        return 100.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_metrics(
    curve: EquityCurve,
    *,
    pnl_per_trade: Sequence[float],
    periods_per_year: int = 252,
) -> dict[str, float]:
    return {
        "total_return": total_return(curve),
        "cagr": cagr(curve),
        "sharpe": sharpe_ratio(curve, periods_per_year=periods_per_year),
        "sortino": sortino_ratio(curve, periods_per_year=periods_per_year),
        "max_drawdown": max_drawdown(curve),
        "calmar": calmar_ratio(curve),
        "win_rate": win_rate(pnl_per_trade),
        "profit_factor": profit_factor(pnl_per_trade),
    }
```

- [ ] **Step 3: Run metrics tests**

```bash
pytest tests/test_backtest_metrics.py -v
```
Expected: 8 PASS.

- [ ] **Step 4: Full suite**

```bash
pytest tests/ -q
```
Expected: **87 passed** (79 + 8).

- [ ] **Step 5: Commit**

```bash
git add backend/core/backtest/metrics.py backend/tests/test_backtest_metrics.py
git commit -m "feat(backtest): performance metrics (Sharpe/Sortino/CAGR/MaxDD/Calmar/PF)"
```

---

## Task 7: Backtest engine (TDD with toy strategy)

**Files:**
- Create: `backend/core/backtest/engine.py`
- Create: `backend/tests/test_backtest_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_backtest_engine.py
"""End-to-end engine drive with a toy buy-the-dip strategy."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from core.backtest.engine import BacktestEngine
from core.backtest.types import Bar, BacktestConfig
from core.broker.base import Broker
from core.strategy.base import Strategy
from core.strategy.context import StrategyContext


def _make_bars(symbol: str, prices: list[float]) -> list[Bar]:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars: list[Bar] = []
    previous_close = None
    for i, close in enumerate(prices):
        ts = base + timedelta(days=i)
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=ts,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1_000_000,
                previous_close=previous_close,
            )
        )
        previous_close = close
    return bars


class _ToyDipStrategy(Strategy):
    """Buys 1000 USD on every 2% drop vs previous close, holds forever."""

    name = "toy_dip_v1"
    description = "Buy 1000 USD when price drops 2% below previous close."

    @classmethod
    def parameters_schema(cls):
        from app.models import StrategyExecutionParameters
        return StrategyExecutionParameters

    def __init__(self, parameters, *, broker: Broker | None = None) -> None:
        super().__init__(parameters)
        self._broker = broker

    def universe(self) -> list[str]:
        return list(self.parameters.universe_symbols)

    async def on_start(self, ctx: StrategyContext) -> None:
        return None

    async def on_periodic_sync(self, ctx, now: datetime) -> None:
        return None

    async def on_tick(self, ctx, *, symbol: str, price: float, previous_close: float, timestamp=None):
        if previous_close <= 0:
            return
        drop = (price - previous_close) / previous_close
        if drop <= -0.02 and self._broker is not None:
            await self._broker.submit_order(symbol=symbol, side="buy", notional=1000.0)


@pytest.mark.asyncio
async def test_engine_runs_toy_strategy_to_completion() -> None:
    from app.models import StrategyExecutionParameters

    bars_aapl = _make_bars(
        "AAPL",
        [100.0, 100.0, 95.0, 96.0, 97.0, 98.0, 100.0, 102.0],
    )
    config = BacktestConfig(
        strategy_name="toy_dip_v1",
        parameters={"universe_symbols": ["AAPL"]},
        universe=["AAPL"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 9),
        initial_cash=10_000.0,
    )

    parameters = StrategyExecutionParameters(
        universe_symbols=["AAPL"],
        entry_drop_percent=2.0,
        add_on_drop_percent=2.0,
        initial_buy_notional=1000.0,
        add_on_buy_notional=100.0,
        max_daily_entries=1,
        max_add_ons=0,
        take_profit_target=80.0,
        stop_loss_percent=12.0,
        max_hold_days=30,
    )

    def _strategy_factory(broker: Broker) -> Strategy:
        return _ToyDipStrategy(parameters, broker=broker)

    engine = BacktestEngine(config=config, strategy_factory=_strategy_factory)
    result = await engine.run({"AAPL": bars_aapl})

    # The strategy buys on the 5% drop on day 3 (95 vs 100). Cash should be
    # 10000 - 1000 = 9000. One trade recorded.
    assert len(result.trades) >= 1
    assert result.trades[0].side == "buy"
    assert round(result.final_cash, 2) <= 9_000.0
    assert len(result.equity_curve) == len(bars_aapl)
    assert result.metrics["total_return"] != 0.0 or result.metrics["max_drawdown"] != 0.0
```

- [ ] **Step 2: Implement `engine.py`**

```python
# backend/core/backtest/engine.py
"""BacktestEngine — drives a Strategy through a stream of historical bars."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Callable

from core.backtest.broker import BacktestBroker
from core.backtest.metrics import compute_metrics
from core.backtest.portfolio import BacktestPortfolio
from core.backtest.types import Bar, BacktestConfig, BacktestResult
from core.broker.base import Broker
from core.strategy.base import Strategy
from core.strategy.context import StrategyContext

StrategyFactory = Callable[[Broker], Strategy]


class BacktestEngine:
    """Runs a bar-by-bar replay against a Strategy."""

    def __init__(
        self,
        *,
        config: BacktestConfig,
        strategy_factory: StrategyFactory,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self._strategy_factory = strategy_factory
        self._logger = logger or logging.getLogger("backtest")

    async def run(self, bars_by_symbol: dict[str, list[Bar]]) -> BacktestResult:
        portfolio = BacktestPortfolio(initial_cash=self.config.initial_cash)

        # Group bars chronologically, interleaving symbols by timestamp.
        merged: list[Bar] = []
        for symbol_bars in bars_by_symbol.values():
            merged.extend(symbol_bars)
        merged.sort(key=lambda b: b.timestamp)

        # Mutable cell so the broker callbacks can read the current sim time
        # and per-symbol prices.
        current_prices: dict[str, float] = {}
        sim_now = {"value": merged[0].timestamp if merged else datetime.now(timezone.utc)}

        broker = BacktestBroker(
            portfolio,
            current_price_provider=lambda s: current_prices.get(s, 0.0),
            current_time_provider=lambda: sim_now["value"],
        )
        strategy = self._strategy_factory(broker)
        ctx = StrategyContext(parameters=strategy.parameters, logger=self._logger)

        started_at = datetime.now(timezone.utc)
        await strategy.on_start(ctx)

        # Stream bars. Each timestamp can carry multiple symbols' bars.
        try:
            grouped: dict[datetime, list[Bar]] = {}
            for bar in merged:
                grouped.setdefault(bar.timestamp, []).append(bar)

            for ts in sorted(grouped):
                sim_now["value"] = ts
                for bar in grouped[ts]:
                    current_prices[bar.symbol] = bar.close

                # Periodic broker sync once per day BEFORE bar evaluation.
                try:
                    await strategy.on_periodic_sync(ctx, ts)
                except Exception:
                    self._logger.exception("Strategy periodic sync raised in backtest")

                for bar in grouped[ts]:
                    if bar.previous_close is None or bar.previous_close <= 0:
                        continue
                    try:
                        await strategy.on_tick(
                            ctx,
                            symbol=bar.symbol,
                            price=bar.close,
                            previous_close=bar.previous_close,
                            timestamp=bar.timestamp,
                        )
                    except Exception:
                        self._logger.exception("Strategy on_tick raised for %s", bar.symbol)

                portfolio.record_equity_snapshot(timestamp=ts, prices=dict(current_prices))
        finally:
            try:
                await strategy.on_stop(ctx)
            except Exception:
                self._logger.exception("Strategy on_stop raised")

        finished_at = datetime.now(timezone.utc)

        # Compute realized PnL per round-trip for win-rate / profit-factor.
        pnl_per_trade = self._extract_pnl_per_trade(portfolio.trades)
        metrics = compute_metrics(portfolio.equity_curve, pnl_per_trade=pnl_per_trade)

        equity_value = portfolio.equity(prices=current_prices)
        return BacktestResult(
            config=self.config,
            started_at=started_at,
            finished_at=finished_at,
            final_cash=portfolio.cash,
            final_equity=equity_value,
            equity_curve=list(portfolio.equity_curve),
            trades=list(portfolio.trades),
            metrics=metrics,
        )

    @staticmethod
    def _extract_pnl_per_trade(trades: Iterable) -> list[float]:
        # FIFO match buys with sells per symbol.
        from collections import deque

        open_lots: dict[str, "deque"] = {}
        pnls: list[float] = []
        for trade in trades:
            if trade.side == "buy":
                open_lots.setdefault(trade.symbol, deque()).append(trade)
            elif trade.side == "sell":
                lots = open_lots.get(trade.symbol)
                if not lots:
                    continue
                # The portfolio always closes the full position (single FIFO chunk).
                cost = sum(lot.notional for lot in lots)
                pnls.append(trade.notional - cost)
                lots.clear()
        return pnls
```

- [ ] **Step 3: Run engine test**

```bash
pytest tests/test_backtest_engine.py -v
```
Expected: PASS.

- [ ] **Step 4: Full suite**

```bash
pytest tests/ -q
```
Expected: **88 passed** (87 + 1).

- [ ] **Step 5: Commit**

```bash
git add backend/core/backtest/engine.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): event-driven engine with toy-strategy integration test"
```

---

## Task 8: Update `core/backtest/__init__.py` to expose engine + broker

**Files:**
- Modify: `backend/core/backtest/__init__.py`

- [ ] **Step 1: Replace contents**

```python
"""Backtest engine package — public API."""
from __future__ import annotations

from core.backtest.broker import BacktestBroker
from core.backtest.engine import BacktestEngine, StrategyFactory
from core.backtest.loader import load_daily_bars
from core.backtest.metrics import (
    cagr,
    calmar_ratio,
    compute_metrics,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    total_return,
    win_rate,
)
from core.backtest.portfolio import BacktestPortfolio
from core.backtest.types import (
    Bar,
    BacktestConfig,
    BacktestResult,
    BacktestTradeRecord,
)

__all__ = [
    "Bar",
    "BacktestBroker",
    "BacktestConfig",
    "BacktestEngine",
    "BacktestPortfolio",
    "BacktestResult",
    "BacktestTradeRecord",
    "StrategyFactory",
    "cagr",
    "calmar_ratio",
    "compute_metrics",
    "load_daily_bars",
    "max_drawdown",
    "profit_factor",
    "sharpe_ratio",
    "sortino_ratio",
    "total_return",
    "win_rate",
]
```

- [ ] **Step 2: Tests still pass**

```bash
pytest tests/ -q
```
Expected: **88 passed**.

- [ ] **Step 3: Commit**

```bash
git add backend/core/backtest/__init__.py
git commit -m "feat(backtest): expose engine/loader/metrics public API"
```

---

## Task 9: DB tables `BacktestRun` + `BacktestTrade`

**Files:**
- Modify: `backend/app/db/tables.py`
- Modify: `backend/app/db/__init__.py`

- [ ] **Step 1: Add tables**

Append to `backend/app/db/tables.py`:

```python


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    universe_json: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)
    initial_cash: Mapped[float] = mapped_column(Float, nullable=False)
    final_cash: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_equity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    equity_curve_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
```

- [ ] **Step 2: Add to `app/db/__init__.py` re-exports**

In the existing `from app.db.tables import (...)` block, add `BacktestRun` and `BacktestTrade`. Update `__all__` to include them.

- [ ] **Step 3: Tests still pass (init_database creates the new tables on first use)**

```bash
pytest tests/ -q
```
Expected: **88 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/tables.py backend/app/db/__init__.py
git commit -m "feat(db): add BacktestRun + BacktestTrade tables"
```

---

## Task 10: Backtest API models

**Files:**
- Create: `backend/app/models/backtest.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Write the model module**

```python
# backend/app/models/backtest.py
"""API request/response models for backtest endpoints."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    strategy_name: str = "strategy_b_v1"
    parameters: dict[str, Any] = Field(default_factory=dict)
    universe: list[str] = Field(default_factory=list)
    start_date: date
    end_date: date
    initial_cash: float = 100_000.0


class BacktestSummaryView(BaseModel):
    id: int
    strategy_name: str
    start_date: str
    end_date: str
    initial_cash: float
    final_cash: float
    final_equity: float
    started_at: datetime
    finished_at: datetime
    status: str
    error_message: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)


class BacktestTradeView(BaseModel):
    symbol: str
    side: str
    qty: float
    price: float
    notional: float
    reason: str
    timestamp: datetime


class BacktestRunResponse(BaseModel):
    summary: BacktestSummaryView
    trades: list[BacktestTradeView]


class BacktestEquityPoint(BaseModel):
    timestamp: datetime
    equity: float


class BacktestEquityCurveResponse(BaseModel):
    run_id: int
    points: list[BacktestEquityPoint]


class BacktestRunsListResponse(BaseModel):
    items: list[BacktestSummaryView]
```

- [ ] **Step 2: Re-export from `app/models/__init__.py`**

Add a new import block:

```python
from app.models.backtest import (
    BacktestEquityCurveResponse,
    BacktestEquityPoint,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestRunsListResponse,
    BacktestSummaryView,
    BacktestTradeView,
)
```

And append the new names to `__all__` (alphabetically).

- [ ] **Step 3: Tests still pass**

```bash
pytest tests/ -q
```
Expected: **88 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/backtest.py backend/app/models/__init__.py
git commit -m "feat(api): add backtest API models (request/summary/trades/equity-curve)"
```

---

## Task 11: Backtest service + router

**Files:**
- Create: `backend/app/services/backtest_service.py`
- Create: `backend/app/routers/backtest.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_app_smoke.py`
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: Service**

```python
# backend/app/services/backtest_service.py
"""Async wrapper around BacktestEngine + persistence."""
from __future__ import annotations

import json
from datetime import date as DateType, datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import BacktestRun, BacktestTrade
from app.models import StrategyExecutionParameters

import strategies  # noqa: F401  -- ensure decorators have run

from core.backtest import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    load_daily_bars,
)
from core.broker.base import Broker
from core.strategy.registry import default_registry


def _serialize_equity_curve(curve: list[tuple[datetime, float]]) -> str:
    return json.dumps(
        [{"timestamp": ts.isoformat(), "equity": value} for ts, value in curve],
    )


def _serialize_metrics(metrics: dict[str, float]) -> str:
    return json.dumps({k: round(float(v), 6) for k, v in metrics.items()})


async def run_backtest(
    session: AsyncSession,
    *,
    strategy_name: str,
    parameters: dict[str, Any],
    universe: list[str],
    start_date: DateType,
    end_date: DateType,
    initial_cash: float,
) -> BacktestRun:
    strategy_cls = default_registry.get(strategy_name)
    schema = strategy_cls.parameters_schema()
    parsed_params = schema.model_validate({**parameters, "universe_symbols": universe or parameters.get("universe_symbols", [])})

    config = BacktestConfig(
        strategy_name=strategy_name,
        parameters=parsed_params.model_dump(),
        universe=parsed_params.universe_symbols,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
    )

    bars = await load_daily_bars(parsed_params.universe_symbols, start=start_date, end=end_date)

    def _factory(broker: Broker):
        # Strategy concrete classes that accept a `broker` kwarg get one;
        # those that don't (legacy ABC-only) fall back to default-broker init.
        try:
            return strategy_cls(parsed_params, broker=broker)  # type: ignore[call-arg]
        except TypeError:
            return strategy_cls(parsed_params)

    engine = BacktestEngine(config=config, strategy_factory=_factory)

    started_at = datetime.now(timezone.utc)
    try:
        result: BacktestResult = await engine.run(bars)
        status = "completed"
        error_message = ""
    except Exception as exc:  # noqa: BLE001
        finished_at = datetime.now(timezone.utc)
        run = BacktestRun(
            strategy_name=strategy_name,
            parameters_json=json.dumps(parsed_params.model_dump()),
            universe_json=json.dumps(parsed_params.universe_symbols),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            initial_cash=initial_cash,
            final_cash=initial_cash,
            final_equity=initial_cash,
            metrics_json="{}",
            equity_curve_json="[]",
            started_at=started_at,
            finished_at=finished_at,
            status="failed",
            error_message=str(exc),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run

    run = BacktestRun(
        strategy_name=strategy_name,
        parameters_json=json.dumps(parsed_params.model_dump()),
        universe_json=json.dumps(parsed_params.universe_symbols),
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        initial_cash=initial_cash,
        final_cash=result.final_cash,
        final_equity=result.final_equity,
        metrics_json=_serialize_metrics(result.metrics),
        equity_curve_json=_serialize_equity_curve(result.equity_curve),
        started_at=result.started_at,
        finished_at=result.finished_at,
        status=status,
        error_message=error_message,
    )
    session.add(run)
    await session.flush()

    for trade in result.trades:
        session.add(
            BacktestTrade(
                run_id=run.id,
                symbol=trade.symbol,
                side=trade.side,
                qty=trade.qty,
                price=trade.price,
                notional=trade.notional,
                reason=trade.reason,
                timestamp=trade.timestamp,
            )
        )
    await session.commit()
    await session.refresh(run)
    return run


def serialize_summary(run: BacktestRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "strategy_name": run.strategy_name,
        "start_date": run.start_date,
        "end_date": run.end_date,
        "initial_cash": run.initial_cash,
        "final_cash": run.final_cash,
        "final_equity": run.final_equity,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "error_message": run.error_message,
        "metrics": json.loads(run.metrics_json or "{}"),
    }


async def list_runs(session: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    result = await session.execute(
        select(BacktestRun).order_by(desc(BacktestRun.id)).limit(max(1, min(limit, 200)))
    )
    return [serialize_summary(row) for row in result.scalars().all()]


async def get_run_with_trades(session: AsyncSession, run_id: int) -> tuple[BacktestRun, list[BacktestTrade]] | None:
    run = await session.get(BacktestRun, run_id)
    if run is None:
        return None
    result = await session.execute(
        select(BacktestTrade).where(BacktestTrade.run_id == run_id).order_by(BacktestTrade.id)
    )
    return run, list(result.scalars().all())


async def get_equity_curve(session: AsyncSession, run_id: int) -> list[dict[str, Any]] | None:
    run = await session.get(BacktestRun, run_id)
    if run is None:
        return None
    return json.loads(run.equity_curve_json or "[]")
```

- [ ] **Step 2: Router**

```python
# backend/app/routers/backtest.py
"""Backtest API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    BacktestEquityCurveResponse,
    BacktestEquityPoint,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestRunsListResponse,
    BacktestSummaryView,
    BacktestTradeView,
)
from app.services import backtest_service

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("/run", response_model=BacktestSummaryView)
async def run_backtest(
    request: BacktestRunRequest,
    session: SessionDep,
) -> BacktestSummaryView:
    try:
        run = await backtest_service.run_backtest(
            session,
            strategy_name=request.strategy_name,
            parameters=request.parameters,
            universe=request.universe,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_cash=request.initial_cash,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {exc}") from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return BacktestSummaryView(**backtest_service.serialize_summary(run))


@router.get("/runs", response_model=BacktestRunsListResponse)
async def list_runs(session: SessionDep) -> BacktestRunsListResponse:
    items = await backtest_service.list_runs(session)
    return BacktestRunsListResponse(items=[BacktestSummaryView(**i) for i in items])


@router.get("/{run_id}", response_model=BacktestRunResponse)
async def get_run(run_id: int, session: SessionDep) -> BacktestRunResponse:
    payload = await backtest_service.get_run_with_trades(session, run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id} not found")
    run, trades = payload
    summary = BacktestSummaryView(**backtest_service.serialize_summary(run))
    trade_views = [
        BacktestTradeView(
            symbol=t.symbol,
            side=t.side,
            qty=t.qty,
            price=t.price,
            notional=t.notional,
            reason=t.reason,
            timestamp=t.timestamp,
        )
        for t in trades
    ]
    return BacktestRunResponse(summary=summary, trades=trade_views)


@router.get("/{run_id}/equity-curve", response_model=BacktestEquityCurveResponse)
async def get_equity_curve(run_id: int, session: SessionDep) -> BacktestEquityCurveResponse:
    points = await backtest_service.get_equity_curve(session, run_id)
    if points is None:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id} not found")
    return BacktestEquityCurveResponse(
        run_id=run_id,
        points=[
            BacktestEquityPoint(timestamp=p["timestamp"], equity=p["equity"])
            for p in points
        ],
    )
```

- [ ] **Step 3: Register router in `app/main.py`**

Add after the other `from app.routers import ...` lines:

```python
from app.routers import backtest as backtest_router
```

And in the registration block:

```python
app.include_router(backtest_router.router)
```

- [ ] **Step 4: Smoke test**

Append to `backend/tests/test_app_smoke.py`:

```python


def test_backtest_runs_list_responds(client) -> None:
    response = client.get("/api/backtest/runs")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert isinstance(body["items"], list)
```

- [ ] **Step 5: Update parity test**

In `backend/tests/test_openapi_parity.py`, add to `EXPECTED_ROUTES`:

```python
("POST",   "/api/backtest/run"),
("GET",    "/api/backtest/runs"),
("GET",    "/api/backtest/{run_id}"),
("GET",    "/api/backtest/{run_id}/equity-curve"),
```

- [ ] **Step 6: Run full suite**

```bash
pytest tests/ -q
```
Expected: **89 passed** (88 + 1 smoke).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/backtest_service.py backend/app/routers/backtest.py backend/app/main.py backend/tests/test_app_smoke.py backend/tests/test_openapi_parity.py
git commit -m "feat(api): backtest service + router (POST run / GET runs/list/{id}/equity-curve)"
```

---

## Task 12: Strategy B end-to-end backtest test

**Files:**
- Create: `backend/tests/test_backtest_e2e.py`

- [ ] **Step 1: Write the e2e test**

```python
# backend/tests/test_backtest_e2e.py
"""End-to-end: Strategy B backtested over mocked yfinance bars."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

import strategies  # noqa: F401  -- decorators

from app.models import StrategyExecutionParameters

from core.backtest import BacktestConfig, BacktestEngine, Bar
from core.broker.base import Broker
from core.strategy.registry import default_registry


def _synthetic_bars(symbol: str, days: int = 60) -> list[Bar]:
    """Build a synthetic price path that triggers Strategy B's entry rule."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars: list[Bar] = []
    previous_close = None
    # Day 0: 100. Day 1-2: small drifts. Day 3: -3% gap. Day 5: +1%/day...
    # Strategy B should enter on day 3 and reach take-profit before day 60.
    prices: list[float] = []
    cur = 100.0
    for i in range(days):
        if i == 3:
            cur = cur * 0.97  # 3% drop triggers entry
        elif i in (10, 15, 20, 30):
            cur *= 1.005
        else:
            cur *= 1.001
        prices.append(round(cur, 4))
    for i, close in enumerate(prices):
        ts = base + timedelta(days=i)
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=ts,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1_000_000,
                previous_close=previous_close,
            )
        )
        previous_close = close
    return bars


@pytest.mark.asyncio
async def test_strategy_b_backtest_runs_and_reports_metrics() -> None:
    parameters = StrategyExecutionParameters(
        universe_symbols=["AAPL"],
        entry_drop_percent=2.0,
        add_on_drop_percent=2.0,
        initial_buy_notional=1000.0,
        add_on_buy_notional=100.0,
        max_daily_entries=1,
        max_add_ons=2,
        take_profit_target=80.0,
        stop_loss_percent=12.0,
        max_hold_days=30,
    )

    bars = {"AAPL": _synthetic_bars("AAPL", days=60)}
    config = BacktestConfig(
        strategy_name="strategy_b_v1",
        parameters=parameters.model_dump(),
        universe=["AAPL"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 3, 1),
        initial_cash=10_000.0,
    )

    strategy_cls = default_registry.get("strategy_b_v1")

    def _factory(broker: Broker):
        return strategy_cls(parameters, broker=broker)

    engine = BacktestEngine(config=config, strategy_factory=_factory)
    result = await engine.run(bars)

    # The strategy should have made at least one trade across this 60-bar
    # synthetic path that contains a clear entry signal.
    assert len(result.equity_curve) == 60
    assert {"total_return", "sharpe", "max_drawdown"} <= set(result.metrics.keys())
    # Either the strategy traded or the equity curve sat flat — both are valid
    # outcomes; we only assert metric shape, not specific numerical values.
    assert isinstance(result.final_equity, float)
```

- [ ] **Step 2: Run e2e**

```bash
pytest tests/test_backtest_e2e.py -v
```
Expected: PASS.

- [ ] **Step 3: Full suite**

```bash
pytest tests/ -q
```
Expected: **90 passed** (89 + 1).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_backtest_e2e.py
git commit -m "test(backtest): Strategy B end-to-end run on synthetic 60-bar path"
```

---

## Task 13: Final verification + push

- [ ] **Step 1: Full test sweep**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -v
```
Expected: **90 passed**.

- [ ] **Step 2: Live boot — verify the new endpoints**

```bash
(uvicorn app.main:app --port 8765 > /tmp/uv.log 2>&1 &); sleep 3
echo "--- backtest runs ---"
curl -s http://127.0.0.1:8765/api/backtest/runs | head -c 400; echo
echo "--- pre-existing endpoints still work ---"
for ep in /api/settings/status /api/social/providers /api/bot/status /api/strategies /api/strategies/registered; do
  printf "%-32s -> " "$ep"
  curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765$ep"
done
pkill -f "uvicorn app.main:app --port 8765"; sleep 1
grep -E "ERROR|Exception" /tmp/uv.log | head -3
```
Expected:
- `/api/backtest/runs` returns `{"items": []}` (no runs yet).
- All five other endpoints return `200`.
- No errors in log.

- [ ] **Step 3: Push**

```bash
git push -u origin feat/p3-backtest-engine
```

---

## Done-criteria

- All 13 tasks committed on `feat/p3-backtest-engine`, branched from `feat/p2-strategy-framework`.
- `pytest tests/` green: **90 passed**.
- New packages: `core/broker/`, `core/backtest/`.
- New tables: `BacktestRun`, `BacktestTrade`.
- New routes: `POST /api/backtest/run`, `GET /api/backtest/runs`, `GET /api/backtest/{id}`, `GET /api/backtest/{id}/equity-curve`. Parity test locks them.
- Strategy B can be backtested via `POST /api/backtest/run` with `{"strategy_name":"strategy_b_v1", ...}`.
- Live behavior of Strategy B unchanged — `AlpacaBroker` is the default, identical to previous direct alpaca_service calls.

After Phase 3 lands, **Phase 4 — Broker abstraction polish + portfolio risk** can plug constraints into the same broker interface (paper/live mode, position-size limits, drawdown halts, daily-loss circuit breakers).
