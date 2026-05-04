# Phase 4 — Risk Layer + RiskGuard Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap every order submission with a composable pre-trade risk layer that can reject orders violating portfolio-wide constraints. Configurable from the API, persisted in DB, and applied to both live trading (via `strategy/runner.py`) and backtests (opt-in flag on `BacktestEngine`). Strategy B's existing trading rules (entry / add-on / exit) are untouched — they still emit orders, the risk layer just blocks the harmful ones.

**Architecture:** A `RiskGuard` decorator wraps any `Broker`, intercepts `submit_order` and `close_position`, runs every active `RiskCheck` policy against the proposed order plus the current portfolio snapshot, and either lets the call through or raises `RiskViolationError`. Each rejection is recorded in the `RiskEvent` table for audit. The active policy set lives in a singleton `RiskPolicyConfig` DB row (JSON-encoded) so the user can tune thresholds via PUT without code changes.

```
                Strategy B engine
                        │ submit_order(...)
                        ▼
                ┌───────────────────┐
                │   RiskGuard       │  pre-trade gate
                │   - load policies │
                │   - evaluate each │
                │   - log events    │
                └───────┬───────────┘
                        │ allow → forward
                        ▼
              AlpacaBroker / BacktestBroker
                        │
                        ▼
                  alpaca_service / portfolio
```

**Tech Stack:** Python 3.13, Pydantic v2, FastAPI 0.135, SQLAlchemy async + aiosqlite. No new top-level deps.

**Out of scope (deferred):**
- Real-time alerting on risk events (Phase 5 — observability layer integrates with existing alerts service).
- Per-strategy policy overrides (only one global policy set in P4; per-strategy comes when multiple strategies coexist).
- Slippage / margin-aware sizing (just hard caps and circuit breakers in P4).
- Frontend UI for editing thresholds — frozen until backend phases done.
- Dynamic policy hot-reload — runner reads config at startup; restart required to apply edits to the live loop. Backtest reads on each run.

---

## File Structure

### New packages
| Path | Responsibility |
|---|---|
| `backend/core/risk/__init__.py` | Re-exports `RiskGuard`, `RiskCheck`, `RiskCheckResult`, `RiskViolationError`, `OrderRequest`, all built-in policies |
| `backend/core/risk/types.py` | `OrderRequest` (proposed order shape), `RiskCheckResult` (allow/deny + reason) |
| `backend/core/risk/errors.py` | `RiskViolationError` exception |
| `backend/core/risk/base.py` | `RiskCheck` ABC: `name`, async `evaluate(request, portfolio_snapshot) -> RiskCheckResult` |
| `backend/core/risk/portfolio_snapshot.py` | `PortfolioSnapshot` dataclass — broker-agnostic view of cash/positions/equity/daily_pnl |
| `backend/core/risk/guard.py` | `RiskGuard(Broker)` decorator class |
| `backend/core/risk/policies/__init__.py` | Re-exports each policy class |
| `backend/core/risk/policies/max_position_size.py` | `MaxPositionSizePolicy` — per-symbol notional cap |
| `backend/core/risk/policies/max_total_exposure.py` | `MaxTotalExposurePolicy` — sum of all open notionals as % of equity |
| `backend/core/risk/policies/max_open_positions.py` | `MaxOpenPositionsPolicy` — concurrent position count |
| `backend/core/risk/policies/max_daily_loss.py` | `MaxDailyLossPolicy` — halt when realized PnL today drops below threshold |
| `backend/core/risk/policies/symbol_blocklist.py` | `SymbolBlocklistPolicy` — explicit deny list |

### Modified files
| File | Change |
|---|---|
| `backend/app/db/tables.py` | Add `RiskPolicyConfig` (singleton row) and `RiskEvent` ORM tables. |
| `backend/app/db/__init__.py` | Re-export `RiskPolicyConfig`, `RiskEvent`. |
| `backend/app/models/__init__.py` | Re-export new risk API models. |
| `backend/app/main.py` | Register `risk_router`. |
| `backend/strategy/runner.py` | After loading the strategy, wrap its broker in `RiskGuard` configured from DB. |
| `backend/core/backtest/engine.py` | `BacktestEngine.run` accepts optional `risk_guard_factory` callable that wraps the BacktestBroker. |
| `backend/app/services/backtest_service.py` | Accept `enable_risk_guard: bool = False`; when true, build a RiskGuard from current DB config. |
| `backend/app/models/backtest.py` | Add `enable_risk_guard: bool = False` to `BacktestRunRequest`. |
| `backend/strategies/strategy_b.py` | Accept the broker through `__init__` as before — wrapping happens upstream so no behavior change here. |
| `backend/tests/test_openapi_parity.py` | Add 3 new risk routes to `EXPECTED_ROUTES`. |

### New files
| Path | Responsibility |
|---|---|
| `backend/app/models/risk.py` | `RiskPolicyConfigView`, `RiskPolicyConfigUpdateRequest`, `RiskEventView`, `RiskEventsResponse` |
| `backend/app/services/risk_service.py` | DB CRUD for config + event log + factory `build_guard_from_config(broker, snapshot_provider)` |
| `backend/app/routers/risk.py` | 3 endpoints: GET config, PUT config, GET events |

### New tests
| File | What it covers |
|---|---|
| `backend/tests/test_risk_policies.py` | Each of the 5 policies in isolation: allow/deny boundary cases |
| `backend/tests/test_risk_guard.py` | Composition: guard runs all checks, raises on first violation, logs event, allows on all-clear |
| `backend/tests/test_app_smoke.py` (append) | Smoke: GET /api/risk/policies, GET /api/risk/events |
| `backend/tests/test_backtest_engine.py` (append) | Backtest with a guard that blocks a symbol returns equity curve unchanged |

### Untouched
- All Phase 0/1/2/3 work other than the listed adjustments.
- Strategy B's trading logic — the engine still calls `self._broker.submit_order(...)`. The broker we hand it is now wrapped, but the wrap is transparent on `allow` decisions.
- Frontend, agent-harness, launcher, Dockerfile, CI workflows.

---

## Pre-flight

- [ ] Confirm baseline (we end Phase 3 at 91 passed):
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **91 passed**.

- [ ] Branch off P3:
```bash
cd ~/NewBirdClaude
git checkout feat/p3-backtest-engine
git checkout -b feat/p4-risk-layer
```

---

## Task 1: Risk types + errors + portfolio snapshot

**Files:**
- Create: `backend/core/risk/__init__.py` (placeholder; full re-exports in Task 7)
- Create: `backend/core/risk/types.py`
- Create: `backend/core/risk/errors.py`
- Create: `backend/core/risk/portfolio_snapshot.py`

- [ ] **Step 1: `types.py`**

```python
"""Value types passed across the risk layer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class OrderRequest:
    """A proposed order, presented to risk policies for approval.

    `notional` (USD) and `qty` are mutually exclusive. `current_price` is the
    broker's last-known price for the symbol, used by policies to convert
    qty-based orders into notional terms.
    """

    symbol: str
    side: str  # "buy" | "sell"
    notional: Optional[float] = None
    qty: Optional[float] = None
    current_price: Optional[float] = None
    requested_at: Optional[datetime] = None

    def estimated_notional(self) -> float:
        """Return the absolute notional of this order in USD, best effort."""
        if self.notional is not None:
            return abs(self.notional)
        if self.qty is not None and self.current_price is not None:
            return abs(self.qty * self.current_price)
        return 0.0


@dataclass(frozen=True)
class RiskCheckResult:
    """Output of a single RiskCheck.evaluate call."""

    allowed: bool
    policy_name: str
    reason: str = ""

    @classmethod
    def allow(cls, policy_name: str, reason: str = "") -> "RiskCheckResult":
        return cls(allowed=True, policy_name=policy_name, reason=reason)

    @classmethod
    def deny(cls, policy_name: str, reason: str) -> "RiskCheckResult":
        return cls(allowed=False, policy_name=policy_name, reason=reason)
```

- [ ] **Step 2: `errors.py`**

```python
"""Risk layer exceptions."""
from __future__ import annotations

from core.risk.types import RiskCheckResult


class RiskViolationError(RuntimeError):
    """Raised when a risk policy denies an order.

    Carries the failing RiskCheckResult so callers (broker wrappers, audit
    code, API error handlers) can introspect the rejection reason.
    """

    def __init__(self, result: RiskCheckResult) -> None:
        super().__init__(f"{result.policy_name}: {result.reason}")
        self.result = result
```

- [ ] **Step 3: `portfolio_snapshot.py`**

```python
"""Broker-agnostic portfolio snapshot consumed by risk policies."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PortfolioPositionView:
    symbol: str
    qty: float
    average_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float


@dataclass
class PortfolioSnapshot:
    """A snapshot of broker state at the moment a risk check runs.

    `realized_pnl_today` is the sum of closed-trade PnL since UTC start-of-day.
    `equity` is cash + sum(market_value of open positions).
    """

    cash: float
    equity: float
    positions: dict[str, PortfolioPositionView] = field(default_factory=dict)
    realized_pnl_today: float = 0.0
    equity_high_water_mark: float = 0.0
```

- [ ] **Step 4: Placeholder `__init__.py`**

```python
"""Risk policy framework. Public API is finalized in Task 7."""
```

- [ ] **Step 5: Smoke test imports**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
python -c "
from core.risk.types import OrderRequest, RiskCheckResult
from core.risk.errors import RiskViolationError
from core.risk.portfolio_snapshot import PortfolioSnapshot, PortfolioPositionView
print('ok', OrderRequest('AAPL', 'buy', notional=1000.0).estimated_notional())
"
```
Expected: `ok 1000.0`.

- [ ] **Step 6: Run baseline tests**

```bash
pytest tests/ -q
```
Expected: **91 passed**.

- [ ] **Step 7: Commit**

```bash
git add backend/core/risk/__init__.py backend/core/risk/types.py backend/core/risk/errors.py backend/core/risk/portfolio_snapshot.py
git commit -m "feat(risk): add OrderRequest/RiskCheckResult/PortfolioSnapshot/RiskViolationError"
```

---

## Task 2: `RiskCheck` ABC

**Files:**
- Create: `backend/core/risk/base.py`

- [ ] **Step 1: Write `base.py`**

```python
"""RiskCheck ABC — the interface every concrete risk policy implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class RiskCheck(ABC):
    """Abstract base for pre-trade risk policies.

    Stateless evaluators: given a proposed order and the current portfolio
    snapshot, return RiskCheckResult.allow or RiskCheckResult.deny.
    """

    name: str = ""

    @abstractmethod
    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        """Return RiskCheckResult; never raise on rule violation."""
```

- [ ] **Step 2: Smoke test**

```bash
python -c "
from core.risk.base import RiskCheck
print('abstract methods:', sorted(RiskCheck.__abstractmethods__))
"
```
Expected: `abstract methods: ['evaluate']`.

- [ ] **Step 3: Tests still pass**

```bash
pytest tests/ -q
```
Expected: **91 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/risk/base.py
git commit -m "feat(risk): define RiskCheck ABC"
```

---

## Task 3: 5 concrete policies (TDD)

**Files:**
- Create: `backend/core/risk/policies/__init__.py`
- Create: `backend/core/risk/policies/max_position_size.py`
- Create: `backend/core/risk/policies/max_total_exposure.py`
- Create: `backend/core/risk/policies/max_open_positions.py`
- Create: `backend/core/risk/policies/max_daily_loss.py`
- Create: `backend/core/risk/policies/symbol_blocklist.py`
- Create: `backend/tests/test_risk_policies.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_risk_policies.py
"""Each policy in isolation: allow/deny boundary cases."""
from __future__ import annotations

import pytest

from core.risk.policies.max_daily_loss import MaxDailyLossPolicy
from core.risk.policies.max_open_positions import MaxOpenPositionsPolicy
from core.risk.policies.max_position_size import MaxPositionSizePolicy
from core.risk.policies.max_total_exposure import MaxTotalExposurePolicy
from core.risk.policies.symbol_blocklist import SymbolBlocklistPolicy
from core.risk.portfolio_snapshot import PortfolioPositionView, PortfolioSnapshot
from core.risk.types import OrderRequest


def _empty_snapshot(cash: float = 100_000.0, equity: float | None = None) -> PortfolioSnapshot:
    return PortfolioSnapshot(cash=cash, equity=equity if equity is not None else cash)


def _snapshot_with_positions(
    *,
    cash: float,
    positions: dict[str, PortfolioPositionView],
    realized_pnl_today: float = 0.0,
) -> PortfolioSnapshot:
    equity = cash + sum(p.market_value for p in positions.values())
    return PortfolioSnapshot(
        cash=cash,
        equity=equity,
        positions=positions,
        realized_pnl_today=realized_pnl_today,
    )


@pytest.mark.asyncio
async def test_max_position_size_allows_below_cap() -> None:
    policy = MaxPositionSizePolicy(max_notional_per_symbol=5_000.0)
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, _empty_snapshot())
    assert result.allowed


@pytest.mark.asyncio
async def test_max_position_size_blocks_when_combined_exceeds_cap() -> None:
    policy = MaxPositionSizePolicy(max_notional_per_symbol=5_000.0)
    snap = _snapshot_with_positions(
        cash=95_000.0,
        positions={
            "AAPL": PortfolioPositionView(
                symbol="AAPL",
                qty=40.0,
                average_entry_price=100.0,
                current_price=110.0,
                market_value=4_400.0,
                unrealized_pl=400.0,
            )
        },
    )
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0, current_price=110.0)
    result = await policy.evaluate(request, snap)
    # Existing 4400 + new 1000 = 5400 > 5000 cap → deny
    assert not result.allowed
    assert "AAPL" in result.reason


@pytest.mark.asyncio
async def test_max_position_size_allows_sell() -> None:
    policy = MaxPositionSizePolicy(max_notional_per_symbol=5_000.0)
    request = OrderRequest(symbol="AAPL", side="sell", qty=10.0, current_price=110.0)
    result = await policy.evaluate(request, _empty_snapshot())
    # Sells reduce position, not increase — allowed.
    assert result.allowed


@pytest.mark.asyncio
async def test_max_total_exposure_allows_below_threshold() -> None:
    policy = MaxTotalExposurePolicy(max_exposure_pct=0.5)
    snap = _snapshot_with_positions(
        cash=80_000.0,
        positions={
            "AAPL": PortfolioPositionView(
                symbol="AAPL", qty=10.0, average_entry_price=100.0,
                current_price=100.0, market_value=1_000.0, unrealized_pl=0.0,
            )
        },
    )
    request = OrderRequest(symbol="MSFT", side="buy", notional=10_000.0)
    result = await policy.evaluate(request, snap)
    # Existing exposure 1000 + new 10000 = 11000; equity 81000; ratio ≈ 0.136 < 0.5
    assert result.allowed


@pytest.mark.asyncio
async def test_max_total_exposure_denies_above_threshold() -> None:
    policy = MaxTotalExposurePolicy(max_exposure_pct=0.5)
    snap = _snapshot_with_positions(
        cash=20_000.0,
        positions={
            "AAPL": PortfolioPositionView(
                symbol="AAPL", qty=350.0, average_entry_price=100.0,
                current_price=100.0, market_value=35_000.0, unrealized_pl=0.0,
            )
        },
    )
    request = OrderRequest(symbol="MSFT", side="buy", notional=10_000.0)
    result = await policy.evaluate(request, snap)
    # Existing exposure 35000 + new 10000 = 45000; equity 55000; ratio ≈ 0.818 > 0.5
    assert not result.allowed


@pytest.mark.asyncio
async def test_max_open_positions_allows_below_count() -> None:
    policy = MaxOpenPositionsPolicy(max_positions=5)
    snap = _snapshot_with_positions(
        cash=90_000.0,
        positions={
            f"S{i}": PortfolioPositionView(
                symbol=f"S{i}", qty=10.0, average_entry_price=10.0,
                current_price=10.0, market_value=100.0, unrealized_pl=0.0,
            )
            for i in range(3)
        },
    )
    request = OrderRequest(symbol="NEW", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, snap)
    assert result.allowed


@pytest.mark.asyncio
async def test_max_open_positions_blocks_at_cap_for_new_symbol() -> None:
    policy = MaxOpenPositionsPolicy(max_positions=3)
    snap = _snapshot_with_positions(
        cash=90_000.0,
        positions={
            f"S{i}": PortfolioPositionView(
                symbol=f"S{i}", qty=10.0, average_entry_price=10.0,
                current_price=10.0, market_value=100.0, unrealized_pl=0.0,
            )
            for i in range(3)
        },
    )
    request = OrderRequest(symbol="NEW", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, snap)
    assert not result.allowed


@pytest.mark.asyncio
async def test_max_open_positions_allows_add_on_to_existing() -> None:
    policy = MaxOpenPositionsPolicy(max_positions=3)
    positions = {
        f"S{i}": PortfolioPositionView(
            symbol=f"S{i}", qty=10.0, average_entry_price=10.0,
            current_price=10.0, market_value=100.0, unrealized_pl=0.0,
        )
        for i in range(3)
    }
    snap = _snapshot_with_positions(cash=90_000.0, positions=positions)
    request = OrderRequest(symbol="S1", side="buy", notional=100.0)
    result = await policy.evaluate(request, snap)
    # Adding to an existing position doesn't grow the position count.
    assert result.allowed


@pytest.mark.asyncio
async def test_max_daily_loss_allows_when_above_threshold() -> None:
    policy = MaxDailyLossPolicy(max_loss_usd=500.0)
    snap = _snapshot_with_positions(cash=99_000.0, positions={}, realized_pnl_today=-200.0)
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, snap)
    assert result.allowed


@pytest.mark.asyncio
async def test_max_daily_loss_blocks_when_loss_exceeded() -> None:
    policy = MaxDailyLossPolicy(max_loss_usd=500.0)
    snap = _snapshot_with_positions(cash=99_000.0, positions={}, realized_pnl_today=-650.0)
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, snap)
    assert not result.allowed


@pytest.mark.asyncio
async def test_max_daily_loss_does_not_block_sells() -> None:
    """Selling should always be allowed even after the daily-loss circuit
    breaker trips — closing positions is how you stop the bleeding."""
    policy = MaxDailyLossPolicy(max_loss_usd=500.0)
    snap = _snapshot_with_positions(cash=99_000.0, positions={}, realized_pnl_today=-650.0)
    request = OrderRequest(symbol="AAPL", side="sell", qty=10.0, current_price=100.0)
    result = await policy.evaluate(request, snap)
    assert result.allowed


@pytest.mark.asyncio
async def test_symbol_blocklist_denies_listed() -> None:
    policy = SymbolBlocklistPolicy(symbols=["GME", "AMC"])
    request = OrderRequest(symbol="GME", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, _empty_snapshot())
    assert not result.allowed


@pytest.mark.asyncio
async def test_symbol_blocklist_allows_unlisted() -> None:
    policy = SymbolBlocklistPolicy(symbols=["GME", "AMC"])
    request = OrderRequest(symbol="AAPL", side="buy", notional=1_000.0)
    result = await policy.evaluate(request, _empty_snapshot())
    assert result.allowed
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_risk_policies.py -v
```
Expected: collection error (modules don't exist yet).

- [ ] **Step 3: Implement each policy**

```python
# backend/core/risk/policies/max_position_size.py
"""Per-symbol notional cap."""
from __future__ import annotations

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class MaxPositionSizePolicy(RiskCheck):
    name = "max_position_size"

    def __init__(self, *, max_notional_per_symbol: float) -> None:
        self.max_notional_per_symbol = float(max_notional_per_symbol)

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.side != "buy":
            return RiskCheckResult.allow(self.name, "sell — not capped")

        existing = portfolio.positions.get(request.symbol)
        existing_notional = existing.market_value if existing else 0.0
        proposed_notional = request.estimated_notional()
        combined = existing_notional + proposed_notional

        if combined > self.max_notional_per_symbol:
            return RiskCheckResult.deny(
                self.name,
                f"{request.symbol} exposure {combined:.2f} > cap {self.max_notional_per_symbol:.2f}",
            )
        return RiskCheckResult.allow(self.name)
```

```python
# backend/core/risk/policies/max_total_exposure.py
"""Sum of all open notionals as percentage of equity."""
from __future__ import annotations

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class MaxTotalExposurePolicy(RiskCheck):
    name = "max_total_exposure"

    def __init__(self, *, max_exposure_pct: float) -> None:
        if not 0 < max_exposure_pct <= 1.0:
            raise ValueError("max_exposure_pct must be in (0, 1].")
        self.max_exposure_pct = float(max_exposure_pct)

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.side != "buy":
            return RiskCheckResult.allow(self.name, "sell — not capped")
        if portfolio.equity <= 0:
            return RiskCheckResult.deny(self.name, "non-positive equity")

        current_exposure = sum(pos.market_value for pos in portfolio.positions.values())
        proposed_exposure = current_exposure + request.estimated_notional()
        ratio = proposed_exposure / portfolio.equity
        if ratio > self.max_exposure_pct:
            return RiskCheckResult.deny(
                self.name,
                f"total exposure ratio {ratio:.3f} > cap {self.max_exposure_pct:.3f}",
            )
        return RiskCheckResult.allow(self.name)
```

```python
# backend/core/risk/policies/max_open_positions.py
"""Concurrent open-position count cap. Adding to an existing position is allowed."""
from __future__ import annotations

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class MaxOpenPositionsPolicy(RiskCheck):
    name = "max_open_positions"

    def __init__(self, *, max_positions: int) -> None:
        self.max_positions = int(max_positions)

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.side != "buy":
            return RiskCheckResult.allow(self.name, "sell — not capped")

        already_open = len(portfolio.positions)
        if request.symbol in portfolio.positions:
            return RiskCheckResult.allow(self.name, "add-on to existing position")
        if already_open >= self.max_positions:
            return RiskCheckResult.deny(
                self.name,
                f"open positions {already_open} >= cap {self.max_positions}",
            )
        return RiskCheckResult.allow(self.name)
```

```python
# backend/core/risk/policies/max_daily_loss.py
"""Daily realized-loss circuit breaker.

Once realized PnL today drops below -max_loss_usd, all new buys are denied.
Sells are still allowed (so the bot can close losing positions and stop
the bleeding).
"""
from __future__ import annotations

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class MaxDailyLossPolicy(RiskCheck):
    name = "max_daily_loss"

    def __init__(self, *, max_loss_usd: float) -> None:
        if max_loss_usd <= 0:
            raise ValueError("max_loss_usd must be > 0.")
        self.max_loss_usd = float(max_loss_usd)

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.side != "buy":
            return RiskCheckResult.allow(self.name, "sell — circuit breaker bypass")

        if portfolio.realized_pnl_today <= -self.max_loss_usd:
            return RiskCheckResult.deny(
                self.name,
                f"daily loss {portfolio.realized_pnl_today:.2f} <= -{self.max_loss_usd:.2f}",
            )
        return RiskCheckResult.allow(self.name)
```

```python
# backend/core/risk/policies/symbol_blocklist.py
"""Explicit deny list."""
from __future__ import annotations

from collections.abc import Iterable

from core.risk.base import RiskCheck
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult


class SymbolBlocklistPolicy(RiskCheck):
    name = "symbol_blocklist"

    def __init__(self, *, symbols: Iterable[str]) -> None:
        self.symbols = {s.upper() for s in symbols if s}

    async def evaluate(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
    ) -> RiskCheckResult:
        if request.symbol.upper() in self.symbols:
            return RiskCheckResult.deny(
                self.name,
                f"{request.symbol} is on the blocklist",
            )
        return RiskCheckResult.allow(self.name)
```

```python
# backend/core/risk/policies/__init__.py
"""Built-in risk policies."""
from __future__ import annotations

from core.risk.policies.max_daily_loss import MaxDailyLossPolicy
from core.risk.policies.max_open_positions import MaxOpenPositionsPolicy
from core.risk.policies.max_position_size import MaxPositionSizePolicy
from core.risk.policies.max_total_exposure import MaxTotalExposurePolicy
from core.risk.policies.symbol_blocklist import SymbolBlocklistPolicy

__all__ = [
    "MaxDailyLossPolicy",
    "MaxOpenPositionsPolicy",
    "MaxPositionSizePolicy",
    "MaxTotalExposurePolicy",
    "SymbolBlocklistPolicy",
]
```

- [ ] **Step 4: Run policy tests**

```bash
pytest tests/test_risk_policies.py -v
```
Expected: 13 PASS.

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -q
```
Expected: **104 passed** (91 + 13).

- [ ] **Step 6: Commit**

```bash
git add backend/core/risk/policies/ backend/tests/test_risk_policies.py
git commit -m "feat(risk): add 5 built-in policies (size/exposure/positions/daily-loss/blocklist)"
```

---

## Task 4: `RiskGuard` decorator (TDD)

**Files:**
- Create: `backend/core/risk/guard.py`
- Create: `backend/tests/test_risk_guard.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_risk_guard.py
"""RiskGuard composes policies and proxies a Broker."""
from __future__ import annotations

from typing import Any, Optional

import pytest

from core.broker.base import Broker
from core.risk.errors import RiskViolationError
from core.risk.guard import RiskGuard
from core.risk.policies.max_position_size import MaxPositionSizePolicy
from core.risk.policies.symbol_blocklist import SymbolBlocklistPolicy
from core.risk.portfolio_snapshot import PortfolioSnapshot


class _FakeBroker(Broker):
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []
        self.closed: list[str] = []

    async def list_positions(self) -> list[dict[str, Any]]:
        return []

    async def list_orders(self, *, status: str = "all", limit: Optional[int] = None) -> list[dict[str, Any]]:
        return []

    async def submit_order(self, *, symbol: str, side: str, notional: Optional[float] = None, qty: Optional[float] = None) -> dict[str, Any]:
        self.submitted.append({"symbol": symbol, "side": side, "notional": notional, "qty": qty})
        return {"id": "ok", "symbol": symbol, "side": side}

    async def close_position(self, symbol: str) -> dict[str, Any]:
        self.closed.append(symbol)
        return {"closed": symbol}


def _empty_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(cash=100_000.0, equity=100_000.0)


@pytest.mark.asyncio
async def test_guard_allows_clean_order() -> None:
    inner = _FakeBroker()
    guard = RiskGuard(
        inner,
        policies=[MaxPositionSizePolicy(max_notional_per_symbol=5_000.0)],
        snapshot_provider=lambda: _empty_snapshot(),
    )
    response = await guard.submit_order(symbol="AAPL", side="buy", notional=1_000.0)
    assert response["id"] == "ok"
    assert inner.submitted == [{"symbol": "AAPL", "side": "buy", "notional": 1_000.0, "qty": None}]
    assert guard.violations == []


@pytest.mark.asyncio
async def test_guard_raises_on_first_violation() -> None:
    inner = _FakeBroker()
    guard = RiskGuard(
        inner,
        policies=[
            SymbolBlocklistPolicy(symbols=["GME"]),
            MaxPositionSizePolicy(max_notional_per_symbol=5_000.0),
        ],
        snapshot_provider=lambda: _empty_snapshot(),
    )
    with pytest.raises(RiskViolationError) as excinfo:
        await guard.submit_order(symbol="GME", side="buy", notional=500.0)
    assert "blocklist" in excinfo.value.result.policy_name
    assert inner.submitted == []
    assert len(guard.violations) == 1
    assert guard.violations[0].policy_name == "symbol_blocklist"


@pytest.mark.asyncio
async def test_guard_passes_through_close_position_without_checks() -> None:
    inner = _FakeBroker()
    guard = RiskGuard(
        inner,
        policies=[SymbolBlocklistPolicy(symbols=["AAPL"])],
        snapshot_provider=lambda: _empty_snapshot(),
    )
    response = await guard.close_position("AAPL")
    # close_position is an exit — should not be gated.
    assert response == {"closed": "AAPL"}


@pytest.mark.asyncio
async def test_guard_proxies_list_methods() -> None:
    inner = _FakeBroker()
    guard = RiskGuard(inner, policies=[], snapshot_provider=lambda: _empty_snapshot())
    assert await guard.list_positions() == []
    assert await guard.list_orders() == []
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_risk_guard.py -v
```
Expected: import error.

- [ ] **Step 3: Implement `guard.py`**

```python
# backend/core/risk/guard.py
"""RiskGuard — wraps a Broker with pre-trade policy checks."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Awaitable, Callable, Optional

from core.broker.base import Broker
from core.risk.base import RiskCheck
from core.risk.errors import RiskViolationError
from core.risk.portfolio_snapshot import PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult

SnapshotProvider = Callable[[], PortfolioSnapshot] | Callable[[], Awaitable[PortfolioSnapshot]]


class RiskGuard(Broker):
    """Decorator: intercept submit_order, run all policies, log violations.

    `snapshot_provider` returns the current PortfolioSnapshot. It can be sync
    or async — the guard awaits if needed. `close_position` and the read-only
    methods (list_positions, list_orders) are NOT gated.
    """

    def __init__(
        self,
        inner: Broker,
        *,
        policies: Sequence[RiskCheck],
        snapshot_provider: SnapshotProvider,
        logger: logging.Logger | None = None,
    ) -> None:
        self._inner = inner
        self._policies = list(policies)
        self._snapshot_provider = snapshot_provider
        self._logger = logger or logging.getLogger("risk.guard")
        self.violations: list[RiskCheckResult] = []

    async def _resolve_snapshot(self) -> PortfolioSnapshot:
        result = self._snapshot_provider()
        if hasattr(result, "__await__"):
            return await result  # type: ignore[no-any-return]
        return result  # type: ignore[return-value]

    async def list_positions(self) -> list[dict[str, Any]]:
        return await self._inner.list_positions()

    async def list_orders(self, *, status: str = "all", limit: Optional[int] = None) -> list[dict[str, Any]]:
        return await self._inner.list_orders(status=status, limit=limit)

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        snapshot = await self._resolve_snapshot()
        request = OrderRequest(
            symbol=symbol,
            side=side,
            notional=notional,
            qty=qty,
            current_price=(snapshot.positions[symbol].current_price if symbol in snapshot.positions else None),
        )
        for policy in self._policies:
            result = await policy.evaluate(request, snapshot)
            if not result.allowed:
                self.violations.append(result)
                self._logger.warning(
                    "RiskGuard rejected %s %s: %s — %s",
                    side,
                    symbol,
                    result.policy_name,
                    result.reason,
                )
                raise RiskViolationError(result)
        return await self._inner.submit_order(symbol=symbol, side=side, notional=notional, qty=qty)

    async def close_position(self, symbol: str) -> dict[str, Any]:
        # Closes are never gated — they are how the system de-risks.
        return await self._inner.close_position(symbol)
```

- [ ] **Step 4: Run guard tests**

```bash
pytest tests/test_risk_guard.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -q
```
Expected: **108 passed** (104 + 4).

- [ ] **Step 6: Commit**

```bash
git add backend/core/risk/guard.py backend/tests/test_risk_guard.py
git commit -m "feat(risk): add RiskGuard broker decorator with composable policies"
```

---

## Task 5: Final `core/risk/__init__.py` re-exports

**Files:**
- Modify: `backend/core/risk/__init__.py`

- [ ] **Step 1: Replace contents**

```python
"""Risk policy framework public API."""
from __future__ import annotations

from core.risk.base import RiskCheck
from core.risk.errors import RiskViolationError
from core.risk.guard import RiskGuard, SnapshotProvider
from core.risk.policies import (
    MaxDailyLossPolicy,
    MaxOpenPositionsPolicy,
    MaxPositionSizePolicy,
    MaxTotalExposurePolicy,
    SymbolBlocklistPolicy,
)
from core.risk.portfolio_snapshot import PortfolioPositionView, PortfolioSnapshot
from core.risk.types import OrderRequest, RiskCheckResult

__all__ = [
    "MaxDailyLossPolicy",
    "MaxOpenPositionsPolicy",
    "MaxPositionSizePolicy",
    "MaxTotalExposurePolicy",
    "OrderRequest",
    "PortfolioPositionView",
    "PortfolioSnapshot",
    "RiskCheck",
    "RiskCheckResult",
    "RiskGuard",
    "RiskViolationError",
    "SnapshotProvider",
    "SymbolBlocklistPolicy",
]
```

- [ ] **Step 2: Smoke**

```bash
python -c "
from core.risk import RiskGuard, RiskCheck, MaxPositionSizePolicy, RiskViolationError
print('ok risk public API')
"
```
Expected: `ok risk public API`.

- [ ] **Step 3: Commit**

```bash
git add backend/core/risk/__init__.py
git commit -m "feat(risk): expose framework public API"
```

---

## Task 6: DB tables `RiskPolicyConfig` + `RiskEvent`

**Files:**
- Modify: `backend/app/db/tables.py`
- Modify: `backend/app/db/__init__.py`

- [ ] **Step 1: Append to `tables.py`**

```python


class RiskPolicyConfig(Base):
    """Singleton row: id=1 holds the active policy configuration JSON."""

    __tablename__ = "risk_policy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class RiskEvent(Base):
    """Audit log: each rejected order produces one row here."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    policy_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # "deny" | "allow"
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 2: Update `app/db/__init__.py`**

Add `RiskPolicyConfig` and `RiskEvent` to the import block from `app.db.tables` and to `__all__` (alphabetically).

- [ ] **Step 3: Tests pass**

```bash
pytest tests/ -q
```
Expected: **108 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/tables.py backend/app/db/__init__.py
git commit -m "feat(db): add RiskPolicyConfig + RiskEvent tables"
```

---

## Task 7: Risk API models + service + router

**Files:**
- Create: `backend/app/models/risk.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/services/risk_service.py`
- Create: `backend/app/routers/risk.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_app_smoke.py`
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: API models**

```python
# backend/app/models/risk.py
"""Risk-layer API models."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RiskPolicyConfigView(BaseModel):
    enabled: bool
    max_position_size_usd: Optional[float] = None
    max_total_exposure_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    max_daily_loss_usd: Optional[float] = None
    blocklist: list[str] = Field(default_factory=list)
    updated_at: Optional[datetime] = None


class RiskPolicyConfigUpdateRequest(BaseModel):
    enabled: bool = True
    max_position_size_usd: Optional[float] = None
    max_total_exposure_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    max_daily_loss_usd: Optional[float] = None
    blocklist: list[str] = Field(default_factory=list)


class RiskEventView(BaseModel):
    id: int
    occurred_at: datetime
    policy_name: str
    decision: str
    reason: str
    symbol: str
    side: str
    notional: Optional[float] = None
    qty: Optional[float] = None


class RiskEventsResponse(BaseModel):
    items: list[RiskEventView]
```

Update `app/models/__init__.py`: import the four new names, append to `__all__` alphabetically.

- [ ] **Step 2: Service**

```python
# backend/app/services/risk_service.py
"""Risk policy CRUD + factory that builds a RiskGuard from DB config.

Snapshot building (cash, equity, positions, realized PnL today) lives here
because both live runner and backtest service need it. We pull from
`alpaca_service` for live and from a `BacktestPortfolio` for backtest.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import RiskEvent, RiskPolicyConfig
from core.broker.base import Broker
from core.risk import (
    MaxDailyLossPolicy,
    MaxOpenPositionsPolicy,
    MaxPositionSizePolicy,
    MaxTotalExposurePolicy,
    PortfolioSnapshot,
    RiskCheck,
    RiskGuard,
    SymbolBlocklistPolicy,
)

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "max_position_size_usd": None,
    "max_total_exposure_pct": None,
    "max_open_positions": None,
    "max_daily_loss_usd": None,
    "blocklist": [],
}


async def get_or_create_config(session: AsyncSession) -> RiskPolicyConfig:
    config = await session.get(RiskPolicyConfig, 1)
    if config is None:
        config = RiskPolicyConfig(id=1, enabled=True, config_json=json.dumps(DEFAULT_CONFIG))
        session.add(config)
        await session.commit()
        await session.refresh(config)
    return config


def _config_to_view(config: RiskPolicyConfig) -> dict[str, Any]:
    body = json.loads(config.config_json or "{}")
    return {
        "enabled": bool(config.enabled),
        "max_position_size_usd": body.get("max_position_size_usd"),
        "max_total_exposure_pct": body.get("max_total_exposure_pct"),
        "max_open_positions": body.get("max_open_positions"),
        "max_daily_loss_usd": body.get("max_daily_loss_usd"),
        "blocklist": list(body.get("blocklist") or []),
        "updated_at": config.updated_at,
    }


async def get_config_view(session: AsyncSession) -> dict[str, Any]:
    config = await get_or_create_config(session)
    return _config_to_view(config)


async def update_config(
    session: AsyncSession,
    *,
    enabled: bool,
    max_position_size_usd: float | None,
    max_total_exposure_pct: float | None,
    max_open_positions: int | None,
    max_daily_loss_usd: float | None,
    blocklist: list[str],
) -> dict[str, Any]:
    config = await get_or_create_config(session)
    config.enabled = bool(enabled)
    config.config_json = json.dumps(
        {
            "max_position_size_usd": max_position_size_usd,
            "max_total_exposure_pct": max_total_exposure_pct,
            "max_open_positions": max_open_positions,
            "max_daily_loss_usd": max_daily_loss_usd,
            "blocklist": [str(s).strip().upper() for s in (blocklist or []) if str(s).strip()],
        }
    )
    await session.commit()
    await session.refresh(config)
    return _config_to_view(config)


async def list_recent_events(session: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    result = await session.execute(
        select(RiskEvent).order_by(desc(RiskEvent.id)).limit(max(1, min(limit, 200)))
    )
    return [
        {
            "id": ev.id,
            "occurred_at": ev.occurred_at,
            "policy_name": ev.policy_name,
            "decision": ev.decision,
            "reason": ev.reason,
            "symbol": ev.symbol,
            "side": ev.side,
            "notional": ev.notional,
            "qty": ev.qty,
        }
        for ev in result.scalars().all()
    ]


def build_policies_from_config(config_dict: dict[str, Any]) -> list[RiskCheck]:
    policies: list[RiskCheck] = []
    if config_dict.get("max_position_size_usd"):
        policies.append(MaxPositionSizePolicy(max_notional_per_symbol=float(config_dict["max_position_size_usd"])))
    if config_dict.get("max_total_exposure_pct"):
        policies.append(MaxTotalExposurePolicy(max_exposure_pct=float(config_dict["max_total_exposure_pct"])))
    if config_dict.get("max_open_positions"):
        policies.append(MaxOpenPositionsPolicy(max_positions=int(config_dict["max_open_positions"])))
    if config_dict.get("max_daily_loss_usd"):
        policies.append(MaxDailyLossPolicy(max_loss_usd=float(config_dict["max_daily_loss_usd"])))
    blocklist = config_dict.get("blocklist") or []
    if blocklist:
        policies.append(SymbolBlocklistPolicy(symbols=blocklist))
    return policies


def wrap_with_guard(
    broker: Broker,
    *,
    policies: list[RiskCheck],
    snapshot_provider: Callable[[], PortfolioSnapshot] | Callable[[], Awaitable[PortfolioSnapshot]],
) -> RiskGuard:
    return RiskGuard(broker, policies=policies, snapshot_provider=snapshot_provider)


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
```

- [ ] **Step 3: Router**

```python
# backend/app/routers/risk.py
"""Risk policy + audit log endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SessionDep, service_error
from app.models import (
    RiskEventsResponse,
    RiskEventView,
    RiskPolicyConfigUpdateRequest,
    RiskPolicyConfigView,
)
from app.services import risk_service

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/policies", response_model=RiskPolicyConfigView)
async def get_policies(session: SessionDep) -> RiskPolicyConfigView:
    try:
        view = await risk_service.get_config_view(session)
    except Exception as exc:
        raise service_error(exc) from exc
    return RiskPolicyConfigView(**view)


@router.put("/policies", response_model=RiskPolicyConfigView)
async def update_policies(
    request: RiskPolicyConfigUpdateRequest,
    session: SessionDep,
) -> RiskPolicyConfigView:
    try:
        view = await risk_service.update_config(
            session,
            enabled=request.enabled,
            max_position_size_usd=request.max_position_size_usd,
            max_total_exposure_pct=request.max_total_exposure_pct,
            max_open_positions=request.max_open_positions,
            max_daily_loss_usd=request.max_daily_loss_usd,
            blocklist=request.blocklist,
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return RiskPolicyConfigView(**view)


@router.get("/events", response_model=RiskEventsResponse)
async def list_events(session: SessionDep) -> RiskEventsResponse:
    try:
        items = await risk_service.list_recent_events(session)
    except Exception as exc:
        raise service_error(exc) from exc
    return RiskEventsResponse(items=[RiskEventView(**i) for i in items])
```

- [ ] **Step 4: Register in `main.py`**

Add `from app.routers import risk as risk_router` (alongside other router imports) and `app.include_router(risk_router.router)` in the registration block.

- [ ] **Step 5: Smoke test**

Append to `backend/tests/test_app_smoke.py`:

```python


def test_risk_policies_endpoint(client) -> None:
    response = client.get("/api/risk/policies")
    assert response.status_code == 200
    body = response.json()
    assert "enabled" in body
    assert "blocklist" in body


def test_risk_events_endpoint(client) -> None:
    response = client.get("/api/risk/events")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert isinstance(body["items"], list)
```

- [ ] **Step 6: Update parity test**

Add to `backend/tests/test_openapi_parity.py::EXPECTED_ROUTES`:
```python
("GET",    "/api/risk/policies"),
("PUT",    "/api/risk/policies"),
("GET",    "/api/risk/events"),
```

- [ ] **Step 7: Run full suite**

```bash
pytest tests/ -q
```
Expected: **110 passed** (108 + 2 smoke).

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/risk.py backend/app/models/__init__.py backend/app/services/risk_service.py backend/app/routers/risk.py backend/app/main.py backend/tests/test_app_smoke.py backend/tests/test_openapi_parity.py
git commit -m "feat(api): risk policy + event log endpoints"
```

---

## Task 8: Backtest engine accepts a RiskGuard factory

**Files:**
- Modify: `backend/core/backtest/engine.py`
- Modify: `backend/app/models/backtest.py`
- Modify: `backend/app/services/backtest_service.py`
- Modify: `backend/tests/test_backtest_engine.py`

The engine currently constructs a `BacktestBroker` and passes it to the strategy factory. Phase 4 lets the caller wrap that broker before the strategy sees it.

- [ ] **Step 1: Add `risk_guard_factory` parameter to engine**

Edit `backend/core/backtest/engine.py`. Update `BacktestEngine.__init__` to accept an optional callable, and in `run()` use it to wrap the broker if provided:

```python
# Add type alias near top
from typing import Callable, Optional
from core.broker.base import Broker

RiskGuardFactory = Callable[[Broker, "PortfolioSnapshotProvider"], Broker]
PortfolioSnapshotProvider = Callable[[], "PortfolioSnapshot"]
```

```python
# Update __init__
def __init__(
    self,
    *,
    config: BacktestConfig,
    strategy_factory: StrategyFactory,
    risk_guard_factory: RiskGuardFactory | None = None,
    logger: logging.Logger | None = None,
) -> None:
    self.config = config
    self._strategy_factory = strategy_factory
    self._risk_guard_factory = risk_guard_factory
    self._logger = logger or logging.getLogger("backtest")
```

```python
# Inside run(), after creating BacktestBroker:
broker = BacktestBroker(...)
if self._risk_guard_factory is not None:
    broker = self._risk_guard_factory(broker, _build_snapshot_provider(portfolio, current_prices))
strategy = self._strategy_factory(broker)
```

Add a helper `_build_snapshot_provider(portfolio, prices) -> Callable[[], PortfolioSnapshot]` that constructs a `PortfolioSnapshot` from the BacktestPortfolio state on demand:

```python
from core.risk.portfolio_snapshot import PortfolioPositionView, PortfolioSnapshot

def _build_snapshot_provider(portfolio, current_prices):
    def _snapshot() -> PortfolioSnapshot:
        positions: dict[str, PortfolioPositionView] = {}
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
        return PortfolioSnapshot(
            cash=portfolio.cash,
            equity=portfolio.equity(prices=current_prices),
            positions=positions,
            realized_pnl_today=0.0,  # backtest is single-day-agnostic; refine later
        )
    return _snapshot
```

- [ ] **Step 2: Append a test**

Add to `backend/tests/test_backtest_engine.py`:

```python


@pytest.mark.asyncio
async def test_engine_with_risk_guard_blocks_buy() -> None:
    """Verifies the engine wires a RiskGuard around the broker."""
    from core.broker.base import Broker
    from core.risk import RiskGuard, SymbolBlocklistPolicy
    from app.models import StrategyExecutionParameters

    bars_aapl = _make_bars("AAPL", [100.0, 100.0, 95.0, 96.0])
    config = BacktestConfig(
        strategy_name="toy_dip_v1",
        parameters={"universe_symbols": ["AAPL"]},
        universe=["AAPL"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 5),
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

    def _risk_factory(broker: Broker, snapshot_provider) -> Broker:
        return RiskGuard(
            broker,
            policies=[SymbolBlocklistPolicy(symbols=["AAPL"])],
            snapshot_provider=snapshot_provider,
        )

    engine = BacktestEngine(
        config=config,
        strategy_factory=_strategy_factory,
        risk_guard_factory=_risk_factory,
    )
    result = await engine.run({"AAPL": bars_aapl})
    # Strategy tries to buy AAPL on the dip, but RiskGuard blocks every buy.
    assert all(t.symbol != "AAPL" or t.side != "buy" for t in result.trades)
    assert result.final_cash == pytest.approx(10_000.0, abs=1e-6)
```

- [ ] **Step 3: Update API request model**

Edit `backend/app/models/backtest.py`. Add field to `BacktestRunRequest`:
```python
enable_risk_guard: bool = False
```

- [ ] **Step 4: Wire into `backtest_service.run_backtest`**

Edit `backend/app/services/backtest_service.py`:

1. Add parameter `enable_risk_guard: bool = False` to `run_backtest`.
2. When `enable_risk_guard` is True:
   - Load `risk_service.get_config_view(session)`
   - Build policies via `risk_service.build_policies_from_config(view)`
   - Pass a `risk_guard_factory` to `BacktestEngine` that wraps the broker with those policies.
3. Update `app/routers/backtest.py::run_backtest` to forward `request.enable_risk_guard` to the service.

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -q
```
Expected: **111 passed** (110 + 1 engine integration).

- [ ] **Step 6: Commit**

```bash
git add backend/core/backtest/engine.py backend/app/models/backtest.py backend/app/services/backtest_service.py backend/app/routers/backtest.py backend/tests/test_backtest_engine.py
git commit -m "feat(backtest): optional risk_guard integration via factory"
```

---

## Task 9: Live runner wraps AlpacaBroker in RiskGuard

**Files:**
- Modify: `backend/strategy/runner.py`

The live runner currently creates a strategy with the default `AlpacaBroker`. Phase 4 changes this to:
1. Open a DB session at startup.
2. Read risk config + build policies.
3. Wrap `AlpacaBroker()` with a `RiskGuard`.
4. Inject the wrapped broker into the strategy.

A snapshot provider for the live broker pulls cash/positions from `alpaca_service.get_account()` + `list_positions()`.

- [ ] **Step 1: Add a live snapshot helper at the top of `runner.py`**

```python
from app.services import alpaca_service as _alpaca_service
from core.risk.portfolio_snapshot import PortfolioPositionView, PortfolioSnapshot


async def _live_portfolio_snapshot() -> PortfolioSnapshot:
    try:
        account = await _alpaca_service.get_account()
    except Exception:
        account = {}
    try:
        positions = await _alpaca_service.list_positions()
    except Exception:
        positions = []

    pos_views: dict[str, PortfolioPositionView] = {}
    for p in positions:
        symbol = str(p.get("symbol", "")).upper()
        if not symbol:
            continue
        try:
            qty = float(p.get("qty", 0) or 0)
            entry = float(p.get("avg_entry_price", p.get("entry_price", 0)) or 0)
            current = float(p.get("current_price", entry) or entry)
            mv = float(p.get("market_value", qty * current) or qty * current)
            upl = float(p.get("unrealized_pl", (current - entry) * qty) or 0)
        except (TypeError, ValueError):
            continue
        pos_views[symbol] = PortfolioPositionView(
            symbol=symbol,
            qty=qty,
            average_entry_price=entry,
            current_price=current,
            market_value=mv,
            unrealized_pl=upl,
        )

    cash = float(account.get("cash", 0) or 0)
    equity = float(account.get("equity", cash) or cash)
    return PortfolioSnapshot(
        cash=cash,
        equity=equity,
        positions=pos_views,
        realized_pnl_today=0.0,  # Phase 5 wires this up via trade-history aggregation.
    )
```

- [ ] **Step 2: Wrap the broker in `_build_active_strategy`**

```python
async def _build_active_strategy():
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.database import AsyncSessionLocal
    from app.services import risk_service

    from core.broker import AlpacaBroker
    from core.risk import RiskGuard

    strategy_display_name, parameters = await strategy_profiles_service.get_active_strategy_execution_profile()
    strategy_cls = default_registry.get(DEFAULT_STRATEGY_NAME)

    # Load risk config from DB and wrap broker.
    base_broker = AlpacaBroker()
    async with AsyncSessionLocal() as session:
        risk_view = await risk_service.get_config_view(session)
    if risk_view.get("enabled"):
        policies = risk_service.build_policies_from_config(risk_view)
        if policies:
            base_broker = RiskGuard(base_broker, policies=policies, snapshot_provider=_live_portfolio_snapshot)

    strategy = strategy_cls(parameters, broker=base_broker)
    logger.info(
        "Loaded strategy %s (display=%r, risk-policies=%d) with universe size %d",
        DEFAULT_STRATEGY_NAME,
        strategy_display_name,
        len(risk_service.build_policies_from_config(risk_view)) if risk_view.get("enabled") else 0,
        len(strategy.universe()),
    )
    return strategy
```

- [ ] **Step 3: Tests still pass (runner is not exercised by pytest, just imported)**

```bash
pytest tests/ -q
python -c "import strategy.runner; print('runner imports ok')"
```
Expected: **111 passed**, runner imports cleanly.

- [ ] **Step 4: Commit**

```bash
git add backend/strategy/runner.py
git commit -m "feat(strategy): live runner wraps AlpacaBroker in RiskGuard from DB config"
```

---

## Task 10: Final verification + push

- [ ] **Step 1: Full test sweep**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -v
```
Expected: **111 passed**, no `on_event` deprecation warnings.

- [ ] **Step 2: Live boot — verify the new endpoints**

```bash
(uvicorn app.main:app --port 8765 > /tmp/uv.log 2>&1 &); sleep 3
echo "--- risk policies ---"
curl -s http://127.0.0.1:8765/api/risk/policies | head -c 400; echo
echo "--- risk events ---"
curl -s http://127.0.0.1:8765/api/risk/events | head -c 200; echo
echo "--- existing endpoints still work ---"
for ep in /api/settings/status /api/social/providers /api/bot/status /api/strategies /api/strategies/registered /api/backtest/runs; do
  printf "%-32s -> " "$ep"
  curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765$ep"
done

echo "--- PUT /api/risk/policies ---"
curl -s -X PUT http://127.0.0.1:8765/api/risk/policies \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "max_position_size_usd": 5000, "blocklist": ["GME"]}' | head -c 400; echo

pkill -f "uvicorn app.main:app --port 8765"; sleep 1
grep -E "ERROR|Exception" /tmp/uv.log | head -3
```
Expected:
- GET /api/risk/policies returns JSON with `enabled` and `blocklist` keys.
- PUT updates and returns the new view.
- All other endpoints stay 200.
- No errors in log.

- [ ] **Step 3: Push**

```bash
git push -u origin feat/p4-risk-layer
```

---

## Done-criteria

- All 10 tasks committed on `feat/p4-risk-layer`, branched from `feat/p3-backtest-engine`.
- `pytest tests/` green: **111 passed**.
- New packages: `core/risk/`, `core/risk/policies/`.
- New tables: `RiskPolicyConfig`, `RiskEvent`.
- New routes: `GET /api/risk/policies`, `PUT /api/risk/policies`, `GET /api/risk/events`. Parity test locks them.
- Live runner wraps `AlpacaBroker` in a `RiskGuard` configured from DB.
- Backtest service supports `enable_risk_guard: true` request flag.
- 5 built-in policies: max_position_size, max_total_exposure, max_open_positions, max_daily_loss, symbol_blocklist.

After Phase 4 lands, **Phase 5 — Observability + alerting** can wire a logger / Prometheus exporter / alert sender into the existing risk-events table, hook strategy-health metrics into the bot status endpoint, and surface the daily PnL aggregator that this phase stubbed.
