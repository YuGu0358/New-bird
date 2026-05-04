# Technical Signal Engine — Retroactive Implementation Doc

> **Retro doc**: this feature shipped in commit `bc1fc8b` on `feat/portfolio-opt`. Captures the design decisions for future contributors who want to add a 5th detector or a new signal kind.

**Goal:** Detect classical buy/sell signals on a symbol's chart (MACD cross, RSI extremes, volume confirmation, support/resistance breakout) and surface them as marker dots on the price chart and as JSON for the Trade Recommendation aggregator.

**Architecture:** Pure-compute detectors under `backend/core/signals/` — no I/O. A `signals_service` pulls OHLCV bars via `chart_service` and dispatches to all 4 detectors. New `GET /api/signals/{symbol}` endpoint. Frontend overlays `<ReferenceDot>` markers on the existing `<AreaChart>`.

**Tech Stack:** Python 3.11, pytest, existing `core.indicators` package for MACD/RSI math reuse, pydantic v2, React 18 + recharts.

---

## File Structure

**Created:**
- `backend/core/signals/__init__.py` — re-exports `Signal`, `SignalDirection`, `SignalKind`
- `backend/core/signals/types.py` — frozen `Signal` dataclass; `ts: Optional[datetime]` because chart bars may be missing the field
- `backend/core/signals/macd_cross.py` — bull/bear MACD line vs signal line
- `backend/core/signals/rsi_levels.py` — RSI<30 oversold bounce + RSI>70 overbought fade
- `backend/core/signals/volume_confirmation.py` — 20-day high/low break with vol > 1.5× avg
- `backend/core/signals/breakout.py` — pure 20-bar high/low close-through
- `backend/app/models/signals.py` — `SignalView`, `SignalsResponse` pydantic
- `backend/app/services/signals_service.py` — orchestrate fetch + detector dispatch
- `backend/app/routers/signals.py` — `GET /api/signals/{symbol}?range=3mo`
- `backend/tests/test_signals_detectors.py` — 9 pure-compute tests
- `frontend-v2/src/components/SignalsMarkers.jsx` — recharts ReferenceDot overlay

**Modified:**
- `backend/app/main.py` — registers signals_router
- `backend/app/models/__init__.py` — re-exports
- `backend/tests/test_openapi_parity.py` — adds `("GET", "/api/signals/{symbol}")`
- `frontend-v2/src/lib/api.js` — `getSignals(symbol, range)` helper
- `frontend-v2/src/components/SymbolPreview.jsx` — parallel `useQuery` + threads signals into `<ChartBlock>`

---

## Reference Source Files

1. `backend/core/indicators/compute.py` — `rsi(values, period)`, `macd(values, fast, slow, signal)` exist there; detectors call these.
2. `backend/app/services/chart_service.get_symbol_chart` — returns `{points: [{timestamp, open, high, low, close, volume}], …}`.
3. `backend/core/workflow/engine.py` — example pure-compute module without I/O. Same testing style (synthetic OHLCV in test fixtures).

---

## Tasks (retroactive — these were the build steps in chronological order)

### Task 1: Signal value object + package skeleton

**Files**: `core/signals/types.py`, `core/signals/__init__.py`

- `SignalKind` is a `Literal` of 8 strings — the 4 buy detectors and 4 sell variants:
  `macd_bull_cross`, `macd_bear_cross`, `rsi_oversold_bounce`, `rsi_overbought_fade`,
  `volume_breakout`, `volume_breakdown`, `price_breakout_high`, `price_breakdown_low`.
- `SignalDirection` is `Literal["buy", "sell"]`.
- `Signal` is a frozen dataclass:
  ```python
  @dataclass(frozen=True)
  class Signal:
      kind: SignalKind
      direction: SignalDirection
      strength: float       # [0, 1]
      ts: Optional[datetime]  # None when source bar lacked timestamp
      bar_index: int
      interpretation: str   # one-line tooltip-ready summary
  ```

Decision: `ts` is Optional rather than required. The QC reviewer initially flagged it as a type-contract violation when the pydantic-typed datetime was non-Optional but bars could carry None — making it Optional and having `signals_service` substitute `datetime.min` in the sort key cleanly handles partial bars without raising.

### Task 2: MACD cross detector

**File**: `core/signals/macd_cross.py`

```python
async def detect_macd_crosses(bars, *, fast=12, slow=26, signal_period=9) -> list[Signal]: ...
```

Calls `core.indicators.compute_indicator("macd", closes, params={...})` which returns `{"macd": [...], "signal": [...], "histogram": [...]}`. Iterates pairwise; emits a Signal whenever `(prev_above, curr_above)` flips.

Strength heuristic: `clip(|macd - signal| / (close × 0.01), 0, 1)` — a hairline cross scores low, a confident divergence scores high.

### Task 3: RSI levels detector

**File**: `core/signals/rsi_levels.py`

Tracks `deepest_oversold` / `deepest_overbought` while RSI is in the zone. Emits the signal on cross-back-out. Strength scales with how deep the prior excursion was — RSI 18→31 cross is stronger than 28→31.

Edge case verified in tests: a flat / neutral series returns `[]` even on long inputs.

### Task 4: Volume confirmation

**File**: `core/signals/volume_confirmation.py`

Two preconditions:
1. Today's close beats the 20-bar high (or low).
2. Today's volume ≥ 1.5× the 20-bar volume average.

Both must hold. A breakout on thin volume is suppressed deliberately — the whole point is "real movement, not a single big buyer".

### Task 5: Range breakout (no volume gate)

**File**: `core/signals/breakout.py`

Same range-break logic as volume_confirmation but without the volume gate. Useful as a less strict signal for momentum-traders. Strength scales with the distance beyond the level.

### Task 6: Pydantic models + service layer

**Files**: `app/models/signals.py`, `app/services/signals_service.py`

```python
class SignalView(BaseModel):
    kind: str
    direction: str
    strength: float
    ts: datetime
    bar_index: int
    interpretation: str

class SignalsResponse(BaseModel):
    symbol: str
    range: str
    interval: str
    signals: list[SignalView]
    generated_at: datetime
```

`signals_service.compute_for_symbol(symbol, range_name)`:
1. Fetch `chart_service.get_symbol_chart(symbol, range_name)`.
2. Run all 4 detectors over the bars.
3. Sort by `ts` ascending (with `datetime.min` fallback for None ts).
4. Return wire-shape dict.

### Task 7: Router + parity

**Files**: `app/routers/signals.py`, `app/main.py`, `tests/test_openapi_parity.py`

```python
@router.get("/{symbol}", response_model=SignalsResponse)
async def get_signals(
    symbol: str = Path(..., pattern=r"^[A-Za-z0-9.\-]{1,16}$"),
    range: str = "3mo",
) -> SignalsResponse:
```

The `Path(..., pattern=...)` constraint was added in the QC follow-up commit (`aa63d37`) to block path-traversal / unbounded strings reaching yfinance.

### Task 8: Frontend marker overlay

**Files**: `frontend-v2/src/components/SignalsMarkers.jsx`, `SymbolPreview.jsx`, `lib/api.js`

`SignalsMarkers` normalizes both bar timestamps and signal timestamps to minute-precision ISO before matching:

```js
function normalizeTs(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toISOString().slice(0, 16);  // YYYY-MM-DDTHH:MM
}
```

Decision rationale: strict string equality (`String(b.t) === String(s.ts)`) silently dropped every marker the first time the chart endpoint emitted `2026-04-30T14:00:00.000Z` and the signals endpoint emitted `2026-04-30T14:00:00+00:00`. Minute-level normalization absorbs format drift while staying coarse enough for both daily and intraday bars.

Marker color: green for `buy`, red for `sell`. Radius scales with `Math.max(3, 3 + s.strength * 4)` — strength 1.0 = 7px, weak signals 3px.

---

## Self-Review Checklist (used after the original commit)

- [x] All 4 detectors have at least one positive test + one negative test.
- [x] Detectors never raise on empty / short input — they return `[]`.
- [x] `compute_for_symbol` sorts by `ts` so the frontend renders in order.
- [x] Frontend matches signals to bars via normalized minute-precision ts.
- [x] OpenAPI parity test has the new route.

## Concerns / Follow-ups

1. **Strength normalization is per-detector, not per-symbol.** A 1.0 strength MACD cross on SPY isn't directly comparable to a 1.0 strength volume breakout on NVDA. If the trade-recommendation aggregator becomes more sophisticated, normalize per-symbol historical distribution.
2. **No RSI divergence detector** (price higher high while RSI lower high). Needs swing-point detection. Phase 2.
3. **No Heikin-Ashi confirmation overlay.**
4. **User-configurable detector thresholds** via runtime_settings (RSI levels, lookback windows). Currently hard-coded.
5. **Per-detector enable/disable flag** in the request — currently always all four run.
6. **Detectors are synchronous within an async function.** For very long histories (>1k bars × 4 detectors) consider running each in a thread.
7. **Volume confirmation assumes daily bars.** On intraday ranges the 20-bar lookback is 20 minutes/hours, which may be too short for "real" volume context.
