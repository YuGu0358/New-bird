# IBKR Broker — Interactive Brokers as a Second Broker Backend

**Status:** Pending. To be executed via `/subagent-driven-development`.

**Goal:** Add Interactive Brokers as a second broker backend alongside Alpaca. Newbird's strategy engine, risk guard, and frontend all already speak the `Broker` interface — this plan plugs IBKR into that same interface so a user with an IBKR Pro account can route their portfolio through it.

**Why this is shippable separately from a "live trading" feature:**
- The `Broker` ABC at `backend/core/broker/base.py` is the only contract we need to satisfy
- All existing risk policies / strategy engine / monitoring code already targets the abstraction — no changes needed downstream
- We ship behind a switch (`BROKER_BACKEND=alpaca|ibkr`, default `alpaca`) so no live behavior changes for users who don't opt in
- Smoke-testing requires a running IB Gateway / TWS, but the implementer doesn't need credentials — every test is mock-based

---

## Architecture

```
                          ┌─────────────────────────────────────┐
                          │  routers/account.py                │
                          │  routers/strategies.py             │
                          │  services/risk_service.py          │
                          │  services/monitoring_service.py    │
                          └──────────────────┬──────────────────┘
                                             │ uses Broker interface
                                             ▼
                          ┌─────────────────────────────────────┐
                          │  core/broker/base.py                │
                          │  Broker (ABC):                       │
                          │    list_positions / list_orders    │
                          │    submit_order / close_position   │
                          │    get_account                      │
                          └──────────────────┬──────────────────┘
                                             │
                  ┌──────────────────────────┴───────────────────────┐
                  │                                                   │
                  ▼                                                   ▼
   ┌─────────────────────────────┐                  ┌─────────────────────────────┐
   │ core/broker/alpaca.py       │                  │ core/broker/ibkr.py (NEW)   │
   │ AlpacaBroker                │                  │ IBKRBroker                  │
   │ → app.services.alpaca_*     │                  │ → app.services.ibkr_*       │
   └─────────────────────────────┘                  └──────────────┬──────────────┘
                                                                   │
                                                                   ▼
                                                  ┌─────────────────────────────┐
                                                  │ ib_async (or ib_insync)     │
                                                  │ TCP socket → IB Gateway     │
                                                  │ on 127.0.0.1:5055 (paper)   │
                                                  │ or :4001 (live)             │
                                                  └─────────────────────────────┘
```

**Tech stack choice — `ib_async` over `ib_insync`:**
- `ib_insync` is the well-known classic but is unmaintained (last release 2023) and pinned to old asyncio patterns
- `ib_async` is its actively-maintained 2025 fork with the same surface API + Python 3.13 support
- Either way: TCP socket to a local IB Gateway / TWS process the user runs; we don't talk to IBKR's REST directly

**Out of scope (deliberate):**
- Real-time market-data subscriptions through IBKR (yfinance / Polygon stays the data source — IBKR is for execution + portfolio reads)
- Options chains via IBKR (yfinance handles those in `options_chain_service`)
- Advanced order types (TWAP / VWAP / iceberg) — only market orders for now, matching what AlpacaBroker exposes
- Multi-account routing within IBKR (we use one account ID at a time)
- Live mode (`:4001`) defaults — users must explicitly toggle paper → live in Settings; live trading without a confirmation prompt is unsafe

---

## File structure

### New
| Path | Responsibility |
|---|---|
| `backend/core/broker/ibkr.py` | `IBKRBroker(Broker)` — adapter to ibkr_service |
| `backend/app/services/ibkr_service.py` | Connection lifecycle + `list_positions / list_orders / submit_order / close_position / get_account` |
| `backend/app/services/ibkr_client.py` | Thin wrapper around the `ib_async` connect / disconnect / event-loop integration |
| `backend/tests/test_ibkr_service.py` | Mock-based unit tests |
| `backend/tests/test_ibkr_broker.py` | Test that `IBKRBroker` satisfies the `Broker` interface and forwards correctly |

### Modified
| File | Change |
|---|---|
| `backend/app/runtime_settings.py` | Add `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID`, `IBKR_ACCOUNT_ID`, `BROKER_BACKEND` |
| `backend/core/broker/__init__.py` | Re-export `IBKRBroker` + a `get_broker()` factory that reads `BROKER_BACKEND` |
| `backend/app/dependencies.py` | New `BrokerDep` dependency that returns the active broker per `BROKER_BACKEND` |
| `backend/app/routers/account.py` | Use `BrokerDep` instead of importing `alpaca_service` directly |
| `backend/app/routers/health.py` | Add an IBKR connection-health probe to readiness checks |
| `frontend-v2/src/pages/SettingsPage.jsx` | Show the 5 new settings + a "broker backend" radio (alpaca | ibkr) |
| `frontend-v2/src/i18n/locales/{en,zh,de,fr}.json` | i18n labels for the 5 new settings + radio |

### Out of touched scope
- `services/alpaca_service.py` — unchanged
- `core/broker/alpaca.py` — unchanged (existing AlpacaBroker stays the default)
- `core/broker/base.py` — interface stays exactly as-is; if it doesn't have `get_account()`, we add it (small spec change documented below)

---

## Pre-flight

- [ ] Branch from `feat/journal` (which itself stems from `feat/p9-code-editor`). New branch: `feat/ibkr-broker`.
- [ ] Baseline: `cd backend && python -m pytest --asyncio-mode=auto -q` → expect **256 passed**.
- [ ] Add `ib_async` to `backend/pyproject.toml` (or `requirements.txt` — match what's there). Pin to a stable version (`ib_async>=1.0.3,<2`).
- [ ] User does NOT need to install IB Gateway during implementation — all tests are mock-based.

---

## Task 1: Extend `Broker` interface with `get_account()` (TDD)

**Files:**
- Modify: `backend/core/broker/base.py` — add abstract `get_account()`
- Modify: `backend/core/broker/alpaca.py` — implement `get_account()` (delegates to `alpaca_service.get_account()`)
- Modify: `backend/tests/test_broker_alpaca_adapter.py` — add a test for the new method

**Spec:**

```python
@abstractmethod
async def get_account(self) -> dict[str, Any]:
    """Return account-level metrics: equity, buying_power, cash, status, etc.

    Shape (broker-agnostic minimum):
        {
            "id":         str | None,    # broker-side account id
            "status":     str,           # 'ACTIVE' | 'RESTRICTED' | ...
            "currency":   str,           # 'USD'
            "equity":     float,         # total account value
            "cash":       float,         # cash balance
            "buying_power": float,       # available buying power
        }
    Returns broker-specific keys in addition; callers should treat the
    above 6 as the contract.
    """
```

The Alpaca adapter just delegates to `app.services.alpaca_service.get_account()`. That function already returns the right shape (verify by reading it).

Test verifies:
- `AlpacaBroker().get_account()` returns a dict with the 6 contract keys
- Patches `alpaca_service.get_account` to return a fake dict and asserts the broker passes it through unchanged

**Acceptance:** All existing tests still green (256). The new test is green. Total: 257.

---

## Task 2: IBKR connection client (mock-tested)

**Files:**
- Create: `backend/app/services/ibkr_client.py`
- Create: `backend/tests/test_ibkr_client.py`

**Spec:**

The client is a thin wrapper around `ib_async`'s `IB().connect()` / `disconnect()`. It owns the lifecycle so the rest of the service can `async with get_client() as ib:` without tracking sockets.

Exports:

```python
class IBKRConfigError(RuntimeError):
    """Raised when IBKR_HOST / IBKR_PORT / IBKR_CLIENT_ID are missing."""

@asynccontextmanager
async def get_client() -> AsyncIterator[IB]:
    """Yields a connected `ib_async.IB` instance. Auto-disconnects on exit.

    Reads IBKR_HOST, IBKR_PORT (int), IBKR_CLIENT_ID (int) from runtime_settings.
    Raises IBKRConfigError if any are missing.
    Raises ConnectionRefusedError if the Gateway is not reachable.
    """

async def is_reachable() -> bool:
    """Lightweight TCP probe used by /api/health/ready. Returns True if a
    connection succeeds within a 2s timeout, False otherwise. Never raises."""
```

Implementation notes:
- `ib_async`'s `IB().connect(host, port, clientId)` is async and returns a Future you can `await`
- `disconnect()` is sync — call it in the `finally` block of the context manager
- Reuse a single `ib_async.IB()` per request; don't try to pool yet (premature)

**Tests (mocks `ib_async.IB` entirely — no live Gateway required):**
- `get_client()` reads the 3 settings and calls `IB.connectAsync(host, port, clientId)` with the right args
- `get_client()` calls `IB.disconnect()` on exit, even when the body raises
- Missing settings → `IBKRConfigError`
- `is_reachable()` returns True when connect succeeds, False on `ConnectionRefusedError` or `asyncio.TimeoutError`, never raises

Use `unittest.mock.patch` against `ib_async.IB` to inject a fake.

**Acceptance:** All tests pass. Pytest 257 → 261 (4 new tests).

---

## Task 3: IBKR service (the bulk of the work)

**Files:**
- Create: `backend/app/services/ibkr_service.py`
- Create: `backend/tests/test_ibkr_service.py`

**Spec — five public functions matching the AlpacaBroker surface:**

```python
async def get_account() -> dict[str, Any]:
    """Reads accountSummary() under IBKR_ACCOUNT_ID. Maps to Newbird shape:
        {id, status, currency, equity, cash, buying_power}"""

async def list_positions() -> list[dict[str, Any]]:
    """positions() filtered to IBKR_ACCOUNT_ID. Each row:
        {symbol, qty, avg_entry_price, market_value, current_price,
         unrealized_pl, side ('long'|'short')}"""

async def list_orders(*, status: str = "all", limit: int | None = None) -> list[dict[str, Any]]:
    """openOrders() + completedOrders() merged. status filter:
        'open'    → only openTrades()
        'closed'  → only completedOrders() within last 7 days
        'all'     → both
    Each row:
        {id, symbol, side, qty, status, submitted_at, filled_avg_price}"""

async def submit_order(*, symbol: str, side: str, notional: float | None = None,
                       qty: float | None = None) -> dict[str, Any]:
    """Wraps a Stock contract + MarketOrder. Either notional ($-amount converted
    to qty via mid-price) or qty (shares). Returns:
        {id, symbol, side, qty, status, submitted_at}"""

async def close_position(symbol: str) -> dict[str, Any]:
    """Submits a market order in the opposite direction of the open position.
    Returns the same shape as submit_order. Raises ValueError if no open
    position for that symbol."""
```

**Implementation notes:**
- Use `ib_async`'s `Stock()` contract for equities, `MarketOrder()` for orders
- `accountSummary()` returns a list of `AccountValue` rows tagged by the field name (`NetLiquidation`, `BuyingPower`, `TotalCashValue`, `AccountType`); pick the right ones and convert
- `IBKR_ACCOUNT_ID` filters multi-account responses
- IBKR side codes: `BUY` / `SELL`. Newbird uses `buy` / `sell` lowercase. Translate at the boundary.
- IBKR uses contracts not just symbols — for now SMART exchange + USD currency
- Symbols are case-sensitive on the Stock contract — pass already-uppercased
- `notional → qty` conversion: use the contract's `marketPrice()` (which returns `nan` if no market data); if NaN, raise `ValueError("market price unavailable for IBKR notional order — pass qty instead")`. Don't fail silently.

**Tests (all mock `ibkr_client.get_client` to yield a fake IB instance):**
- `get_account()` happy path: fake returns `accountSummary` rows, service maps to the 6-key dict
- `get_account()` raises `IBKRConfigError` if account_id setting is missing
- `list_positions()` filters by `IBKR_ACCOUNT_ID`, ignores rows from other accounts
- `list_orders(status='open')` returns only open orders (not completed)
- `list_orders(status='closed', limit=5)` truncates correctly
- `submit_order(qty=10, side='buy')` builds the right Stock + MarketOrder
- `submit_order(notional=5000)` converts via mid-price; raises `ValueError` if mid is NaN
- `close_position("NVDA")` reads the open position, submits opposite-side order
- `close_position("XYZ")` raises `ValueError` when no open position

The fake IB instance is just a `Mock()` whose methods are `AsyncMock`. No real socket. ~12 tests total.

**Acceptance:** All tests pass. Pytest 261 → 273 (12 new tests).

---

## Task 4: IBKRBroker adapter + broker factory + dependency

**Files:**
- Create: `backend/core/broker/ibkr.py` — `IBKRBroker(Broker)` adapter
- Modify: `backend/core/broker/__init__.py` — `get_broker()` factory
- Modify: `backend/app/dependencies.py` — `BrokerDep` FastAPI dependency
- Create: `backend/tests/test_ibkr_broker.py`

**Spec:**

```python
# core/broker/ibkr.py
class IBKRBroker(Broker):
    """Adapter — every method delegates to ibkr_service."""
    async def get_account(self) -> dict[str, Any]:
        return await ibkr_service.get_account()
    async def list_positions(self) -> list[dict[str, Any]]:
        return await ibkr_service.list_positions()
    # ... etc

# core/broker/__init__.py
def get_broker() -> Broker:
    """Read BROKER_BACKEND from runtime_settings; return AlpacaBroker by default,
    IBKRBroker if BROKER_BACKEND='ibkr'."""

# app/dependencies.py
def _resolve_broker() -> Broker:
    return get_broker()

BrokerDep = Annotated[Broker, Depends(_resolve_broker)]
```

**Tests:**
- `IBKRBroker.get_account()` calls `ibkr_service.get_account()` (patched)
- Same for list_positions / list_orders / submit_order / close_position
- `get_broker()` returns `AlpacaBroker` when `BROKER_BACKEND` unset
- `get_broker()` returns `IBKRBroker` when `BROKER_BACKEND='ibkr'`
- `get_broker()` falls back to `AlpacaBroker` (with a warning log) for unknown values

**Acceptance:** Pytest 273 → 280 (7 new tests).

---

## Task 5: Wire `BrokerDep` into account router + readiness probe

**Files:**
- Modify: `backend/app/routers/account.py`
- Modify: `backend/app/routers/health.py`
- Modify: `backend/tests/test_app_smoke.py`

**Spec:**

1. **`account.py`**: today the handlers import `app.services.alpaca_service` directly. Replace those direct imports with `BrokerDep` so the same routes serve whichever backend is selected. Don't change response shapes.

2. **`health.py`**: add an entry to the readiness checks for `ibkr.reachable` — calls `ibkr_client.is_reachable()`. Returns `ok=True` when alpaca-mode is selected (skip — IBKR not in use) or when reachable. `ok=False` only when `BROKER_BACKEND=ibkr` AND the Gateway is unreachable.

3. **`test_app_smoke.py`**: existing tests still pass with the broker-dep refactor (alpaca-mode default). Add one new smoke test that verifies `/api/health/ready` returns the IBKR check key.

**Acceptance:** Pytest 280 → 281 (1 new smoke test) + every existing test still green.

---

## Task 6: Settings page integration (frontend)

**Files:**
- Modify: `backend/app/runtime_settings.py` — register the 5 new settings (IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID, IBKR_ACCOUNT_ID, BROKER_BACKEND)
- Modify: `frontend-v2/src/pages/SettingsPage.jsx` — render them
- Modify: `frontend-v2/src/i18n/locales/{en,zh,de,fr}.json` — labels + hints for each

**Spec:**

5 settings with the following defaults / hints:

| Key | Required | Default | Hint |
|---|---|---|---|
| `BROKER_BACKEND` | no | `alpaca` | "Which broker to route through. `alpaca` (default) or `ibkr`. Switching to `ibkr` requires a running IB Gateway." |
| `IBKR_HOST` | no | `127.0.0.1` | "Host where IB Gateway / TWS is running. Default localhost." |
| `IBKR_PORT` | no | `5055` | "5055 = paper, 4001 = live. Set in IB Gateway → Configuration → API." |
| `IBKR_CLIENT_ID` | no | `1` | "Each connection needs a unique integer. Use any 1-32 unless you run multiple bots." |
| `IBKR_ACCOUNT_ID` | no | `""` | "Your IBKR account ID, e.g. DU1234567 (paper) or U1234567 (live). Required only for `ibkr` backend." |

The Settings page renders all 5 in a new "Broker (IBKR)" group below the Alpaca group. `BROKER_BACKEND` is a dropdown / radio; the rest are plain text inputs.

i18n keys go under `settings.labels.{ibkrHost, ibkrPort, ibkrClientId, ibkrAccountId, brokerBackend}` plus `settings.hints.*`.

**Acceptance:**
- Frontend build clean
- All 5 settings render in en/zh/de/fr
- Saving them via PUT /api/settings persists (existing behavior — no new code needed)

---

## Task 7: Final integration verify + commit

- Full pytest: ≥ 281 passed (was 256, +25)
- Frontend build clean
- Curl the health endpoint:
  - Default mode (BROKER_BACKEND unset): `/api/health/ready` shows `ibkr.reachable.ok=true` (skip case)
- Live IBKR smoke (only if user has Gateway running and credentials configured — implementer skips this if no credentials are available, just documents the curl commands)
- Commit on the branch — one logical commit per task
- Branch ready to merge — DO NOT merge or push

**Acceptance:**
- `feat/ibkr-broker` branch on top of `feat/journal`
- 7 logical commits
- No regressions
- `BROKER_BACKEND` defaults to `alpaca` → existing users see zero behavior change
- A user can later install IB Gateway, set the 5 settings on the Settings page, and immediately route through IBKR

---

## Done-criteria

- 7 commits on `feat/ibkr-broker`
- pytest ≥ 281 passing
- New routes (none — all existing routes get a broker-agnostic backend)
- Frontend Settings page shows the IBKR group in 4 languages
- All existing AlpacaBroker tests still pass (Alpaca path unchanged)
- A user with `BROKER_BACKEND=ibkr` + a running Gateway + correct settings can:
  - List positions
  - List orders
  - Submit a market order
  - Close a position
  - View account equity / cash / buying_power
- The `Broker` ABC at `core/broker/base.py` now has `get_account()` (small backward-compatible spec extension)

---

## Risks / open questions

1. **`ib_async` API stability:** the package is young and there may be small differences vs. ib_insync. Implementer should pin a known-good version (`>=1.0.3,<2`).
2. **Async-loop integration:** `ib_async` has its own event loop quirks. Implementer should use the documented "as-async-context" pattern; if there's friction, escalate as DONE_WITH_CONCERNS rather than fight the framework.
3. **Mock realism:** the tests use mocks all the way down; we'll find out what's wrong only when a real IB Gateway is plugged in. Worst case, a follow-up PR fixes ad-hoc bugs from real-world testing.
4. **No live tests in CI:** the user's local machine will be the smoke-test environment. Document the curl commands clearly in Task 7 so the user can validate manually.
