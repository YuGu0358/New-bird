# Phase 2 — Strategy Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a pluggable `Strategy` ABC + registry under `backend/core/strategy/`, refactor existing Strategy B into the first concrete `@register_strategy("strategy_b_v1")` implementation, and rewire `backend/strategy/runner.py` to be strategy-agnostic. Behavior of Strategy B remains identical end-to-end. This unblocks Phase 3 (backtest engine reuses the same `Strategy` interface to drive historical bars) and Phase 4 (broker abstraction sits between Strategy and execution).

**Architecture:** A clean separation between *framework* and *concrete strategies*:

- `backend/core/strategy/` — pure-framework code: `Strategy` ABC, `Signal`/`Action` types, `StrategyParameters` base, `StrategyContext`, `StrategyRegistry`. Knows nothing about Alpaca, Polygon, Strategy B specifics, or trading rules.
- `backend/strategies/` — concrete implementations registered via `@register_strategy("name")`. First (and currently only) one: `StrategyB` wraps the existing `StrategyBEngine` (which we leave logic-untouched).
- `backend/strategy/runner.py` — strategy-agnostic. Loads `(strategy_name, parameters)` from `strategy_profiles_service`, looks up the class in the registry, instantiates, drives the event loop via the ABC methods.
- `backend/app/routers/strategies.py` gains `GET /api/strategies/registered` exposing the registry to the frontend.
- `backend/app/services/strategy_profiles_service.py` — minimally changed: `_normalize_parameters` now consults the registry (so future strategies can ship their own parameter schemas), but Strategy B params keep working unchanged. The 850-line file's bigger restructuring is deferred (it's mostly OpenAI-driven description-to-params analysis, orthogonal to the strategy framework).

**Tech Stack:** Python 3.13, Pydantic v2, FastAPI 0.135. No new deps.

**Out of scope (deferred):**
- Backtesting engine (Phase 3 — will consume the framework added here).
- Broker abstraction (Phase 4).
- DB-tracked `strategy_runs` table (Phase 3 needs it for backtest run records, defer).
- Splitting `strategy_profiles_service.py`'s OpenAI/AI-analysis logic (incidental cleanup, separate small task later).
- Multiple concrete strategies beyond Strategy B (the framework supports them; adding one is its own work).

---

## File Structure

### New packages
| Package | Responsibility |
|---|---|
| `backend/core/__init__.py` | Empty package marker |
| `backend/core/strategy/__init__.py` | Re-exports public API: `Strategy`, `StrategyContext`, `StrategyRegistry`, `register_strategy`, `Signal`, `OrderIntent`, `StrategyParameters` |
| `backend/core/strategy/parameters.py` | `StrategyParameters` Pydantic base — common fields all strategies share |
| `backend/core/strategy/signals.py` | `OrderIntent` dataclass (side, symbol, notional/qty, reason, kind), `SignalType` enum |
| `backend/core/strategy/context.py` | `StrategyContext` — handle passed to strategy methods (logger, parameters, broker shim TBD in P4) |
| `backend/core/strategy/base.py` | `Strategy` ABC — defines lifecycle: `parameters_schema()`, `universe()`, `on_start()`, `on_periodic_sync()`, `on_tick()`, `on_stop()` |
| `backend/core/strategy/registry.py` | `StrategyRegistry` singleton + `@register_strategy("name")` decorator |
| `backend/strategies/__init__.py` | Imports each concrete strategy module so `@register_strategy` runs at startup |
| `backend/strategies/strategy_b.py` | `class StrategyB(Strategy)` registered as `"strategy_b_v1"`, wraps existing `StrategyBEngine` |

### Modified files
| File | Change |
|---|---|
| `backend/strategy/runner.py` | Import strategies package (registers them); load strategy class from registry by name; instantiate; drive via ABC methods. No more direct `from strategy.strategy_b import StrategyBEngine`. |
| `backend/app/routers/strategies.py` | Add `GET /api/strategies/registered` route. |
| `backend/app/services/strategy_profiles_service.py` | `_normalize_parameters` consults registry for the active strategy's parameter schema. Keep all AI-analysis code untouched. |
| `backend/tests/test_openapi_parity.py` | Add new route to `EXPECTED_ROUTES`. |
| `backend/tests/test_strategy_engine.py` | If it imports `StrategyBEngine` directly, it stays — internal engine class unchanged. Otherwise no edit. |

### New tests
| File | What it covers |
|---|---|
| `backend/tests/test_strategy_registry.py` | Decorator registers, lookup works, duplicate name raises, unknown name raises |
| `backend/tests/test_strategy_b_registration.py` | `StrategyB` is registered as `strategy_b_v1`, `parameters_schema()` returns `StrategyExecutionParameters`, instantiation from params works |

### Untouched
- `backend/strategy/strategy_b.py` (the engine logic stays — Strategy B internals don't change)
- All other services, routers, models, db, tests
- Frontend
- Strategy B's existing behavior, signals, exit rules, take-profit, stop-loss, etc.

---

## Pre-flight

- [ ] Confirm baseline:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **60 passed**.

- [ ] Branch off P1:
```bash
cd ~/NewBirdClaude
git checkout refactor/p1-structural-cleanup
git checkout -b feat/p2-strategy-framework
```

---

## Task 1: Create `core/` foundation (signals, parameters, context)

**Files:**
- Create: `backend/core/__init__.py`
- Create: `backend/core/strategy/__init__.py` (placeholder, fleshed out in Task 4)
- Create: `backend/core/strategy/signals.py`
- Create: `backend/core/strategy/parameters.py`
- Create: `backend/core/strategy/context.py`

- [ ] **Step 1: `backend/core/__init__.py`**

```python
"""Framework code shared across the trading platform.

`core` is intentionally free of provider-specific imports (Alpaca, Polygon,
yfinance). It defines the abstract surfaces (Strategy ABC, signals, broker
interface in later phases). Concrete implementations live under
`backend/strategies/`, `backend/services/`, etc.
"""
```

- [ ] **Step 2: `backend/core/strategy/__init__.py` (placeholder)**

```python
"""Strategy framework: ABC + registry + signal/parameter primitives.

Public API (filled in Task 4 after registry exists):
    Strategy, StrategyContext, StrategyRegistry, register_strategy,
    StrategyParameters, OrderIntent, SignalType
"""
```

- [ ] **Step 3: `backend/core/strategy/signals.py`**

```python
"""Strategy → execution layer signal types.

Strategies emit `OrderIntent` records describing *what* they want to do. The
runner / broker layer translates intents into actual orders. Keeping intents
separate from broker calls is what makes backtesting (Phase 3) possible: the
backtest engine consumes the same intents but resolves them against historical
bars instead of an Alpaca account.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SignalType(str, Enum):
    ENTRY = "entry"
    ADD_ON = "add_on"
    EXIT_TAKE_PROFIT = "exit_take_profit"
    EXIT_STOP_LOSS = "exit_stop_loss"
    EXIT_TIMEOUT = "exit_timeout"
    EXIT_MANUAL = "exit_manual"


@dataclass(frozen=True)
class OrderIntent:
    """A strategy's request to open or close a position.

    Either `notional` or `qty` is set, never both. The runner decides which
    broker call to use based on which is present.
    """

    symbol: str
    side: str  # "buy" | "sell"
    signal_type: SignalType
    reason: str
    notional: Optional[float] = None
    qty: Optional[float] = None
    requested_at: Optional[datetime] = None
```

- [ ] **Step 4: `backend/core/strategy/parameters.py`**

```python
"""Base parameter model that every strategy extends.

Concrete strategies provide their own subclass with extra fields. The
framework only assumes `universe_symbols` exists since the runner needs to
know which symbols to subscribe to.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrategyParameters(BaseModel):
    """Common parameter surface every strategy must expose.

    Strategies extend this with their own fields (entry/exit thresholds,
    sizing rules, etc.). The framework only relies on `universe_symbols`.
    """

    model_config = ConfigDict(extra="forbid")

    universe_symbols: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: `backend/core/strategy/context.py`**

```python
"""StrategyContext — the handle passed to strategy lifecycle methods.

Phase 2 keeps this minimal (logger + parameters). Phase 4 adds a broker
handle here so strategies can submit orders without importing alpaca_service
directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models import StrategyExecutionParameters

# Type alias for now — generic enough that any concrete strategy's params
# subclass can be passed. When Phase 4 introduces the Broker interface, this
# will gain a `broker` field.
StrategyParameters = StrategyExecutionParameters  # noqa: E305


@dataclass
class StrategyContext:
    parameters: StrategyParameters
    logger: logging.Logger
```

> Reasoning for Step 5: rather than introduce a brand-new framework parameter type that duplicates `StrategyExecutionParameters` (already used everywhere), Phase 2 reuses the existing one. Phase 3+ may grow a generic base if/when a second strategy needs different fields.

- [ ] **Step 6: Smoke test the imports**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
python -c "
from core.strategy.signals import OrderIntent, SignalType
from core.strategy.parameters import StrategyParameters
from core.strategy.context import StrategyContext
print('ok', SignalType.ENTRY.value, list(StrategyParameters.model_fields))
"
```
Expected: `ok entry ['universe_symbols']`

- [ ] **Step 7: Run baseline tests**

```bash
pytest tests/ -q
```
Expected: **60 passed** (no new tests yet, just verifying no regressions from new modules).

- [ ] **Step 8: Commit**

```bash
git add backend/core/
git commit -m "feat(core): add strategy framework primitives (signals, parameters, context)"
```

---

## Task 2: Define `Strategy` ABC

**Files:**
- Create: `backend/core/strategy/base.py`

- [ ] **Step 1: Write `base.py`**

```python
"""Strategy ABC — the interface every concrete strategy must implement.

Lifecycle (driven by the runner):

    strategy = StrategyClass(parameters)
    await strategy.on_start(ctx)
    while running:
        if periodic_sync_due:
            await strategy.on_periodic_sync(ctx, now)
        for tick in incoming_quotes:
            await strategy.on_tick(ctx, tick)
    await strategy.on_stop(ctx)

Strategies do NOT submit orders directly in Phase 2 — they mutate their own
in-memory state and call broker functions internally (preserving Strategy B's
current behavior). Phase 4 introduces an OrderIntent return type and a Broker
shim on the context, completing the abstraction.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.models import StrategyExecutionParameters

from core.strategy.context import StrategyContext


class Strategy(ABC):
    """Abstract base for all trading strategies."""

    #: Stable identifier used by registry and DB. Concrete classes override.
    name: str = ""

    #: One-line human-readable description shown in admin UI.
    description: str = ""

    @classmethod
    @abstractmethod
    def parameters_schema(cls) -> type[StrategyExecutionParameters]:
        """Return the Pydantic model class describing this strategy's params.

        Used by the API to surface a parameter schema to the frontend, and by
        the profile service to validate user-supplied params before saving.
        """

    def __init__(self, parameters: StrategyExecutionParameters) -> None:
        self.parameters = parameters

    @abstractmethod
    def universe(self) -> list[str]:
        """Symbols the runner should subscribe to for this strategy."""

    @abstractmethod
    async def on_start(self, ctx: StrategyContext) -> None:
        """One-time setup (hydrate state from broker, etc.)."""

    @abstractmethod
    async def on_periodic_sync(self, ctx: StrategyContext, now: datetime) -> None:
        """Periodic broker reconciliation (positions, open orders, P&L)."""

    @abstractmethod
    async def on_tick(
        self,
        ctx: StrategyContext,
        *,
        symbol: str,
        price: float,
        previous_close: float,
        timestamp: Any | None = None,
    ) -> None:
        """Per-quote evaluation. Implementation may submit orders, mutate
        position state, schedule exits, etc."""

    async def on_stop(self, ctx: StrategyContext) -> None:
        """Optional teardown hook. Default is no-op."""
        return None
```

- [ ] **Step 2: Smoke test**

```bash
python -c "
from core.strategy.base import Strategy
print('Strategy abstract methods:', sorted(Strategy.__abstractmethods__))
"
```
Expected: `Strategy abstract methods: ['on_periodic_sync', 'on_start', 'on_tick', 'parameters_schema', 'universe']`

- [ ] **Step 3: Tests still pass**

```bash
pytest tests/ -q
```
Expected: **60 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/strategy/base.py
git commit -m "feat(core): define Strategy ABC with lifecycle methods"
```

---

## Task 3: Strategy registry + decorator

**Files:**
- Create: `backend/core/strategy/registry.py`
- Create: `backend/tests/test_strategy_registry.py`

- [ ] **Step 1: Write the failing test FIRST**

```python
# backend/tests/test_strategy_registry.py
"""Strategy registry behavior."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.models import StrategyExecutionParameters

from core.strategy.base import Strategy
from core.strategy.context import StrategyContext
from core.strategy.registry import (
    StrategyAlreadyRegisteredError,
    StrategyNotFoundError,
    StrategyRegistry,
    register_strategy,
)


def _make_dummy_strategy(name: str) -> type[Strategy]:
    class DummyStrategy(Strategy):
        @classmethod
        def parameters_schema(cls):
            return StrategyExecutionParameters

        def universe(self) -> list[str]:
            return self.parameters.universe_symbols

        async def on_start(self, ctx: StrategyContext) -> None:
            pass

        async def on_periodic_sync(self, ctx, now: datetime) -> None:
            pass

        async def on_tick(self, ctx, *, symbol, price, previous_close, timestamp=None):
            pass

    DummyStrategy.name = name
    return DummyStrategy


def test_register_and_lookup() -> None:
    registry = StrategyRegistry()
    cls = _make_dummy_strategy("dummy_v1")
    registry.register("dummy_v1", cls)
    assert registry.get("dummy_v1") is cls
    assert "dummy_v1" in registry.list_names()


def test_duplicate_registration_raises() -> None:
    registry = StrategyRegistry()
    registry.register("dup", _make_dummy_strategy("dup"))
    with pytest.raises(StrategyAlreadyRegisteredError):
        registry.register("dup", _make_dummy_strategy("dup"))


def test_unknown_lookup_raises() -> None:
    registry = StrategyRegistry()
    with pytest.raises(StrategyNotFoundError):
        registry.get("nonexistent")


def test_decorator_registers_into_default_registry() -> None:
    """The @register_strategy decorator binds to the module-level registry."""
    from core.strategy import registry as registry_module

    cls = _make_dummy_strategy("decorator_test_v1")
    decorated = register_strategy("decorator_test_v1")(cls)
    assert decorated is cls
    assert registry_module.default_registry.get("decorator_test_v1") is cls
    # Cleanup so this test is idempotent across runs.
    registry_module.default_registry._strategies.pop("decorator_test_v1", None)
```

- [ ] **Step 2: Run test, verify it fails**

```bash
pytest tests/test_strategy_registry.py -v
```
Expected: FAIL with `ImportError: cannot import name 'StrategyRegistry' from 'core.strategy.registry'` or similar.

- [ ] **Step 3: Implement `registry.py`**

```python
# backend/core/strategy/registry.py
"""Strategy registry + @register_strategy decorator.

Concrete strategies decorate themselves with @register_strategy("name") at
import time. Importing the `backend/strategies` package triggers all
decorators, populating the module-level `default_registry`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    from core.strategy.base import Strategy


class StrategyAlreadyRegisteredError(RuntimeError):
    """Raised when two classes try to register the same name."""


class StrategyNotFoundError(KeyError):
    """Raised when looking up an unregistered strategy name."""


class StrategyRegistry:
    """Holds the mapping from strategy-name strings to Strategy subclasses."""

    def __init__(self) -> None:
        self._strategies: dict[str, type["Strategy"]] = {}

    def register(self, name: str, strategy_cls: type["Strategy"]) -> None:
        if name in self._strategies and self._strategies[name] is not strategy_cls:
            raise StrategyAlreadyRegisteredError(
                f"Strategy name {name!r} is already registered to "
                f"{self._strategies[name].__module__}.{self._strategies[name].__name__}"
            )
        self._strategies[name] = strategy_cls

    def get(self, name: str) -> type["Strategy"]:
        if name not in self._strategies:
            raise StrategyNotFoundError(f"No strategy registered as {name!r}")
        return self._strategies[name]

    def list_names(self) -> list[str]:
        return sorted(self._strategies.keys())

    def items(self) -> list[tuple[str, type["Strategy"]]]:
        return sorted(self._strategies.items())


default_registry = StrategyRegistry()


T = TypeVar("T", bound="type[Strategy]")


def register_strategy(name: str) -> Callable[[T], T]:
    """Class decorator: register the decorated Strategy subclass under `name`."""

    def _decorator(cls: T) -> T:
        cls.name = name  # type: ignore[attr-defined]
        default_registry.register(name, cls)
        return cls

    return _decorator
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_strategy_registry.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -q
```
Expected: **64 passed** (60 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add backend/core/strategy/registry.py backend/tests/test_strategy_registry.py
git commit -m "feat(core): add StrategyRegistry + @register_strategy decorator with tests"
```

---

## Task 4: Flesh out `core/strategy/__init__.py` re-exports

**Files:**
- Modify: `backend/core/strategy/__init__.py`

- [ ] **Step 1: Write the public API export**

Replace the placeholder content with:

```python
"""Strategy framework public API."""
from __future__ import annotations

from core.strategy.base import Strategy
from core.strategy.context import StrategyContext, StrategyParameters
from core.strategy.parameters import StrategyParameters as StrategyParametersBase
from core.strategy.registry import (
    StrategyAlreadyRegisteredError,
    StrategyNotFoundError,
    StrategyRegistry,
    default_registry,
    register_strategy,
)
from core.strategy.signals import OrderIntent, SignalType

__all__ = [
    "OrderIntent",
    "SignalType",
    "Strategy",
    "StrategyAlreadyRegisteredError",
    "StrategyContext",
    "StrategyNotFoundError",
    "StrategyParameters",
    "StrategyParametersBase",
    "StrategyRegistry",
    "default_registry",
    "register_strategy",
]
```

- [ ] **Step 2: Verify imports**

```bash
python -c "
from core.strategy import (
    Strategy, StrategyContext, StrategyRegistry, register_strategy,
    OrderIntent, SignalType, default_registry,
)
print('all ok')
"
```
Expected: `all ok`.

- [ ] **Step 3: Tests pass**

```bash
pytest tests/ -q
```
Expected: **64 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/strategy/__init__.py
git commit -m "feat(core): expose Strategy framework public API"
```

---

## Task 5: Refactor Strategy B as a registered concrete strategy

**Files:**
- Create: `backend/strategies/__init__.py`
- Create: `backend/strategies/strategy_b.py`
- Create: `backend/tests/test_strategy_b_registration.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_strategy_b_registration.py
"""Verify Strategy B registers correctly via the new framework."""
from __future__ import annotations

from app.models import StrategyExecutionParameters

# Import the strategies package to trigger @register_strategy decorators.
import strategies  # noqa: F401  pyright: ignore

from core.strategy import default_registry
from core.strategy.base import Strategy


def test_strategy_b_is_registered() -> None:
    cls = default_registry.get("strategy_b_v1")
    assert issubclass(cls, Strategy)
    assert cls.name == "strategy_b_v1"


def test_strategy_b_parameters_schema_is_strategy_execution_parameters() -> None:
    cls = default_registry.get("strategy_b_v1")
    assert cls.parameters_schema() is StrategyExecutionParameters


def test_strategy_b_can_be_instantiated_with_default_parameters() -> None:
    cls = default_registry.get("strategy_b_v1")
    parameters = StrategyExecutionParameters(
        universe_symbols=["AAPL", "MSFT"],
        entry_drop_percent=2.0,
        add_on_drop_percent=2.0,
        initial_buy_notional=1000.0,
        add_on_buy_notional=100.0,
        max_daily_entries=3,
        max_add_ons=3,
        take_profit_target=80.0,
        stop_loss_percent=12.0,
        max_hold_days=30,
    )
    strategy = cls(parameters)
    assert strategy.universe() == ["AAPL", "MSFT"]
```

- [ ] **Step 2: Run test, verify it fails**

```bash
pytest tests/test_strategy_b_registration.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'strategies'`.

- [ ] **Step 3: Create `backend/strategies/__init__.py`**

```python
"""Concrete trading strategies. Importing this package registers all of them.

The runner imports `strategies` once at startup so the decorators run before
anyone looks up a strategy by name.
"""
from __future__ import annotations

# Each concrete strategy module triggers @register_strategy on import.
from strategies import strategy_b  # noqa: F401
```

- [ ] **Step 4: Create `backend/strategies/strategy_b.py`**

```python
"""Strategy B as the first registered concrete strategy.

Wraps the existing StrategyBEngine without changing its trading logic. The
wrapper translates the framework's lifecycle methods into engine method calls
and converts API-level StrategyExecutionParameters into the engine's
StrategyExecutionConfig dataclass.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import StrategyExecutionParameters

from core.strategy.base import Strategy
from core.strategy.context import StrategyContext
from core.strategy.registry import register_strategy

from strategy.strategy_b import StrategyBEngine, StrategyExecutionConfig


def _to_engine_config(
    params: StrategyExecutionParameters,
    *,
    strategy_name: str = "strategy_b_v1",
) -> StrategyExecutionConfig:
    """Translate API-level params to the engine's internal dataclass."""
    return StrategyExecutionConfig(
        universe=list(params.universe_symbols),
        entry_drop_threshold=params.entry_drop_percent / 100,
        add_on_drop_threshold=params.add_on_drop_percent / 100,
        initial_buy_notional=params.initial_buy_notional,
        add_on_buy_notional=params.add_on_buy_notional,
        max_daily_entries=params.max_daily_entries,
        max_add_ons=params.max_add_ons,
        take_profit_target=params.take_profit_target,
        stop_loss_threshold=params.stop_loss_percent / 100,
        max_hold_days=params.max_hold_days,
        strategy_name=strategy_name,
    )


@register_strategy("strategy_b_v1")
class StrategyB(Strategy):
    """Fixed-notional dollar-cost-down strategy.

    Buys 1000 USD when a name in the universe drops 2% from the previous
    close, adds 100 USD per additional 2% drop (max 3 add-ons), exits at a
    fixed 80 USD profit target, 12% capital stop-loss, or 30-day timeout.
    """

    description = "Fixed-notional dollar-cost-down strategy on the default 20-name universe."

    @classmethod
    def parameters_schema(cls) -> type[StrategyExecutionParameters]:
        return StrategyExecutionParameters

    def __init__(self, parameters: StrategyExecutionParameters) -> None:
        super().__init__(parameters)
        self._engine = StrategyBEngine(_to_engine_config(parameters))

    @property
    def engine(self) -> StrategyBEngine:
        """Expose the underlying engine for the runner to drive."""
        return self._engine

    def universe(self) -> list[str]:
        return list(self._engine.config.universe)

    async def on_start(self, ctx: StrategyContext) -> None:
        await self._engine.sync_from_broker()
        await self._engine.evaluate_broker_positions()

    async def on_periodic_sync(self, ctx: StrategyContext, now: datetime) -> None:
        await self._engine.sync_from_broker()
        await self._engine.evaluate_broker_positions(now)

    async def on_tick(
        self,
        ctx: StrategyContext,
        *,
        symbol: str,
        price: float,
        previous_close: float,
        timestamp: Any | None = None,
    ) -> None:
        await self._engine.process_tick(
            symbol=symbol,
            current_price=price,
            previous_close=previous_close,
            timestamp=timestamp,
        )
```

- [ ] **Step 5: Run the new test, verify it passes**

```bash
pytest tests/test_strategy_b_registration.py -v
```
Expected: 3 PASS.

- [ ] **Step 6: Run full suite**

```bash
pytest tests/ -q
```
Expected: **67 passed** (60 + 4 + 3).

- [ ] **Step 7: Commit**

```bash
git add backend/strategies/ backend/tests/test_strategy_b_registration.py
git commit -m "feat(strategies): register Strategy B via new framework as strategy_b_v1"
```

---

## Task 6: Refactor `strategy/runner.py` to load via registry

**Files:**
- Modify: `backend/strategy/runner.py`

- [ ] **Step 1: Update `runner.py`**

Open `backend/strategy/runner.py` and replace its body with:

```python
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

import strategies  # noqa: F401  -- triggers @register_strategy decorators

from app.database import init_database
from app.services import polygon_service, strategy_profiles_service

from core.strategy.context import StrategyContext
from core.strategy.registry import default_registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BROKER_SYNC_INTERVAL_SECONDS = 10
QUOTE_POLL_INTERVAL_SECONDS = 5

# Until strategy_profiles supports per-profile strategy_type, treat every
# active profile as Strategy B. Phase 4+ will add that field.
DEFAULT_STRATEGY_NAME = "strategy_b_v1"


async def _build_active_strategy():
    """Resolve the active strategy class + parameters from the profiles service."""
    strategy_display_name, parameters = await strategy_profiles_service.get_active_strategy_execution_profile()
    strategy_cls = default_registry.get(DEFAULT_STRATEGY_NAME)
    strategy = strategy_cls(parameters)
    logger.info(
        "Loaded strategy %s (display=%r) with universe size %d",
        DEFAULT_STRATEGY_NAME,
        strategy_display_name,
        len(strategy.universe()),
    )
    return strategy


async def main() -> None:
    await init_database()

    strategy = await _build_active_strategy()
    ctx = StrategyContext(parameters=strategy.parameters, logger=logger)

    await strategy.on_start(ctx)

    previous_close_cache: dict[str, tuple[date, float]] = {}
    last_broker_sync_at = datetime.now(timezone.utc)

    async def handle_msg(message: dict[str, object]) -> None:
        nonlocal last_broker_sync_at
        symbol = str(message.get("symbol", "")).upper()
        if not symbol:
            return

        price = float(message.get("price", 0.0) or 0.0)
        if price <= 0:
            return

        now = datetime.now(timezone.utc)
        if (now - last_broker_sync_at).total_seconds() >= BROKER_SYNC_INTERVAL_SECONDS:
            try:
                await strategy.on_periodic_sync(ctx, now)
                last_broker_sync_at = now
            except Exception:
                logger.exception("Strategy periodic sync failed")

        previous_close = message.get("previous_close")
        if previous_close is None:
            today = now.date()
            cached_item = previous_close_cache.get(symbol)
            if cached_item is not None and cached_item[0] == today:
                previous_close = cached_item[1]

        if previous_close is None:
            try:
                previous_close = await polygon_service.get_previous_close(symbol)
                previous_close_cache[symbol] = (
                    now.date(),
                    float(previous_close),
                )
            except Exception as exc:
                logger.warning("Skipping %s because previous close could not be loaded: %s", symbol, exc)
                return

        try:
            await strategy.on_tick(
                ctx,
                symbol=symbol,
                price=price,
                previous_close=float(previous_close),
                timestamp=message.get("timestamp"),
            )
        except Exception:
            logger.exception("Strategy evaluation failed for %s", symbol)

    try:
        while True:
            try:
                await polygon_service.stream_quotes(
                    strategy.universe(),
                    handle_msg,
                    poll_seconds=QUOTE_POLL_INTERVAL_SECONDS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Polygon quote stream stopped unexpectedly. Restarting in 5 seconds.")
                await asyncio.sleep(5)
    finally:
        try:
            await strategy.on_stop(ctx)
        except Exception:
            logger.exception("Strategy on_stop hook raised")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify the runner module still imports cleanly**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
python -c "
import strategy.runner as r
print('runner ok, default strategy =', r.DEFAULT_STRATEGY_NAME)
"
```
Expected: `runner ok, default strategy = strategy_b_v1`.

- [ ] **Step 3: Existing strategy engine tests still pass**

```bash
pytest tests/test_strategy_engine.py -v
```
Expected: PASS (the engine logic is unchanged).

- [ ] **Step 4: Full suite**

```bash
pytest tests/ -q
```
Expected: **67 passed**.

- [ ] **Step 5: Commit**

```bash
git add backend/strategy/runner.py
git commit -m "refactor(strategy): runner loads strategy via registry, not direct import"
```

---

## Task 7: Add `GET /api/strategies/registered` endpoint

**Files:**
- Modify: `backend/app/routers/strategies.py`
- Modify: `backend/app/models/strategies.py` (add response model)
- Modify: `backend/tests/test_app_smoke.py` (add smoke test)
- Modify: `backend/tests/test_openapi_parity.py` (add new route to inventory)

- [ ] **Step 1: Add response models**

Append to `backend/app/models/strategies.py`:

```python


class RegisteredStrategyEntry(BaseModel):
    name: str
    description: str
    parameters_schema: dict[str, Any]


class RegisteredStrategiesResponse(BaseModel):
    items: list[RegisteredStrategyEntry]
```

Add `from typing import Any` at the top of the file if not already present, then export the new names from `backend/app/models/__init__.py`:

```python
from app.models.strategies import (
    QuantBrainFactorAnalysis,
    QuantBrainFactorAnalysisRequest,
    RegisteredStrategiesResponse,
    RegisteredStrategyEntry,
    StoredStrategy,
    # ... existing names ...
)
```

(Add `RegisteredStrategiesResponse` and `RegisteredStrategyEntry` to `__all__` too.)

- [ ] **Step 2: Add the route**

Append to `backend/app/routers/strategies.py`:

```python


@router.get("/registered", response_model=RegisteredStrategiesResponse, tags=["strategies"])
async def list_registered_strategies() -> RegisteredStrategiesResponse:
    """Return every strategy registered in the framework registry.

    Frontend uses this to render parameter schemas in the strategy editor.
    """
    # Import here so registration decorators run at first request rather than
    # at app boot. (At app boot the routers import early; the strategies
    # package may not be loaded yet, which would yield an empty list.)
    import strategies  # noqa: F401

    from core.strategy.registry import default_registry

    items: list[RegisteredStrategyEntry] = []
    for name, cls in default_registry.items():
        items.append(
            RegisteredStrategyEntry(
                name=name,
                description=cls.description,
                parameters_schema=cls.parameters_schema().model_json_schema(),
            )
        )
    return RegisteredStrategiesResponse(items=items)
```

> Make sure `RegisteredStrategiesResponse` and `RegisteredStrategyEntry` are imported at the top of `routers/strategies.py`:
> ```python
> from app.models import (
>     ...,
>     RegisteredStrategiesResponse,
>     RegisteredStrategyEntry,
> )
> ```

- [ ] **Step 3: Add smoke test**

Append to `backend/tests/test_app_smoke.py`:

```python


def test_strategies_registered_lists_strategy_b(client) -> None:
    response = client.get("/api/strategies/registered")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    names = [item["name"] for item in body["items"]]
    assert "strategy_b_v1" in names
    strategy_b = next(item for item in body["items"] if item["name"] == "strategy_b_v1")
    assert strategy_b["description"]
    assert "properties" in strategy_b["parameters_schema"]
```

- [ ] **Step 4: Add the new route to OpenAPI parity**

In `backend/tests/test_openapi_parity.py`, append `("GET", "/api/strategies/registered")` to `EXPECTED_ROUTES`.

- [ ] **Step 5: Run smoke + parity**

```bash
pytest tests/test_app_smoke.py tests/test_openapi_parity.py -v
```
Expected: all pass, including the new smoke test.

- [ ] **Step 6: Full suite**

```bash
pytest tests/ -q
```
Expected: **68 passed** (67 + 1 new).

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/strategies.py backend/app/models/strategies.py backend/app/models/__init__.py backend/tests/test_app_smoke.py backend/tests/test_openapi_parity.py
git commit -m "feat(api): add GET /api/strategies/registered listing framework strategies"
```

---

## Task 8: Wire registry into `_normalize_parameters` (parameter validation)

**Files:**
- Modify: `backend/app/services/strategy_profiles_service.py`

The current `_normalize_parameters` clamps Strategy B-specific parameter ranges. After Phase 2, parameter validation should still work for Strategy B, but new strategies in the future could supply their own ranges via the registry. For Phase 2, the change is conservative: prefer the registry's `parameters_schema()` when validating, falling back to the existing clamping logic for Strategy B.

- [ ] **Step 1: Read `_normalize_parameters`**

Open `backend/app/services/strategy_profiles_service.py` and locate `_normalize_parameters` (around line 133). Note its signature:

```python
def _normalize_parameters(parameters: StrategyExecutionParameters) -> StrategyExecutionParameters:
```

It currently does numeric clamping + universe deduplication. Phase 2 leaves the body completely intact — we just add a registry-aware preflight: if the registered strategy's `parameters_schema()` is `StrategyExecutionParameters`, the existing logic applies. If a future strategy supplies a different schema, this function returns the input unchanged for that strategy (no clamping).

- [ ] **Step 2: Edit `_normalize_parameters`**

At the top of the function body, BEFORE the existing logic, add:

```python
    # Registry preflight: if the active strategy uses a non-Strategy-B parameter
    # schema, skip the Strategy-B-specific clamping below and trust the schema.
    try:
        import strategies  # noqa: F401  -- ensure decorators have run
        from core.strategy.registry import default_registry, StrategyNotFoundError

        try:
            strategy_cls = default_registry.get("strategy_b_v1")
        except StrategyNotFoundError:
            strategy_cls = None
        if strategy_cls is not None and strategy_cls.parameters_schema() is not StrategyExecutionParameters:
            return parameters
    except Exception:
        # Never block a save on framework wiring issues.
        pass
```

> Reasoning: this is intentionally defensive. Phase 2 has only Strategy B; the schema check always passes through to the existing logic. The hook is here so that Phase 3+'s additional strategies can opt out of Strategy-B-specific clamping by declaring their own schema.

- [ ] **Step 3: Tests still pass**

```bash
pytest tests/ -q
```
Expected: **68 passed**. (`test_strategy_profiles_service.py::test_normalize_parameters_*` should still cover Strategy B clamping behavior unchanged.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/strategy_profiles_service.py
git commit -m "refactor(profiles): consult registry before applying Strategy-B-specific clamping"
```

---

## Task 9: Final verification + push

- [ ] **Step 1: Full test sweep**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -v
```
Expected: **68 passed**, no `on_event` deprecation warnings.

- [ ] **Step 2: Live boot — verify the new endpoint**

```bash
(uvicorn app.main:app --port 8765 > /tmp/uv.log 2>&1 &); sleep 3
echo "--- registered strategies ---"
curl -s http://127.0.0.1:8765/api/strategies/registered | head -c 600; echo
echo "--- existing endpoints still work ---"
for ep in /api/settings/status /api/social/providers /api/bot/status /api/strategies; do
  printf "%-30s -> " "$ep"
  curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765$ep"
done
pkill -f "uvicorn app.main:app --port 8765"; sleep 1
grep -E "ERROR|Exception" /tmp/uv.log | head -3
```
Expected:
- `/api/strategies/registered` returns JSON with `items` containing at least `strategy_b_v1`.
- All four other endpoints return `200`.
- No errors in log.

- [ ] **Step 3: Push branch**

```bash
git push -u origin feat/p2-strategy-framework
```

---

## Done-criteria

- All 8 tasks committed on `feat/p2-strategy-framework`, branched from `refactor/p1-structural-cleanup`.
- `pytest tests/` green: **68 passed**.
- New `core/strategy/` framework package exists and is logic-clean (no broker/data imports).
- `strategies/strategy_b.py` is the first registered concrete strategy via `@register_strategy("strategy_b_v1")`.
- `strategy/runner.py` is strategy-agnostic; runs Strategy B via the framework, not direct import.
- `GET /api/strategies/registered` returns the registry contents with parameter JSON schemas.
- Strategy B's runtime behavior is byte-identical to before (engine code untouched, just wrapped).
- `strategy_profiles_service.py` has a registry-aware preflight in `_normalize_parameters`.

After Phase 2 lands, **Phase 3 — Backtesting Engine** can plug into the same `Strategy` interface to drive historical bar replay, with Strategy B as the first backtested strategy.
