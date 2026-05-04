# Trade Recommendation Aggregator — Retroactive Implementation Doc

> **Retro doc**: this feature shipped in commit `64d5506` on `feat/portfolio-opt`. Documents the rule-based synthesis of cost basis + signals + custom stops into a concrete actionable stance.

**Goal:** Closes the trade-assistant trio (cost basis → signals → recommendation). Combine the three preceding data sources into one "what should I do right now" card with concrete stances. Pure deterministic rules — no LLM in this path; the AI Council does the LLM-narrative variant.

**Architecture:** `trade_recommendation_service` reads cost basis, fetches the latest price, pulls recent signals, applies a priority-ordered rule chain, and returns one or more `TradeStanceView` entries. Frontend renders a color-coded card on the EquityResearchPage Overview tab.

**Tech Stack:** Python 3.11 + FastAPI + pydantic v2; React + lucide icons.

---

## File Structure

**Created:**
- `backend/app/models/trade_recommendation.py` — `TradeStanceView`, `TradeRecommendationView`
- `backend/app/services/trade_recommendation_service.py` — pure rule-based aggregator
- `backend/app/routers/trade_recommendation.py` — `GET /api/trade-recommendations/{symbol}`
- `backend/tests/test_trade_recommendation_service.py` — 5 fixture tests with `chart_service` and `signals_service` mocked
- `frontend-v2/src/components/TradeRecommendationCard.jsx` — stance card UI

**Modified:**
- `backend/app/main.py` — registers router
- `backend/app/models/__init__.py` — re-exports
- `backend/tests/test_openapi_parity.py` — new route entry
- `frontend-v2/src/lib/api.js` — `getTradeRecommendation(symbol, opts)` helper
- `frontend-v2/src/pages/EquityResearchPage.jsx` — embeds `<TradeRecommendationCard>` at top of Overview

---

## Reference

1. `backend/app/services/position_costs_service.py` — `get_one(session, broker_account_id, ticker)` returns avg / shares / custom stops.
2. `backend/app/services/signals_service.py` — `compute_for_symbol(symbol, range_name)` returns the `signals` list.
3. `backend/app/services/chart_service.py` — used to read the latest close.

---

## Tasks (retroactive)

### Task 1: Pydantic shapes

```python
class TradeStanceView(BaseModel):
    action: str   # "buy" | "sell" | "hold" | "wait" | "stop_triggered" | "tp_triggered"
    confidence: float
    headline: str
    rationale: list[str]

class TradeRecommendationView(BaseModel):
    symbol: str
    current_price: Optional[float]
    has_position: bool
    avg_cost_basis: Optional[float]
    total_shares: Optional[float]
    unrealized_pnl_pct: Optional[float]
    custom_stop_loss: Optional[float]
    custom_take_profit: Optional[float]
    recent_signals_count: int
    stances: list[TradeStanceView]
    generated_at: datetime
```

Each `TradeStanceView` is a single actionable line. Multiple may be returned (current MVP returns just one per request, but the schema allows future expansion: e.g. "stop triggered + consider re-entry").

### Task 2: Service rule chain

```python
async def recommend_for_symbol(
    session,
    *, symbol, broker_account_id=None, range_name="3mo",
) -> dict:
```

Priority-ordered rules:

1. **Hard stop-loss**: if `has_position and price <= custom_stop_loss` → emit `stop_triggered` stance with `confidence=1.0`. Short-circuits — no further stances appended.
2. **Hard take-profit**: same shape, opposite direction.
3. **Signal tally**: sum `strength` per direction across the 5 most-recent signals.
   - If `buy_strength > sell_strength × 1.3` → `buy` (no position) or `hold` (existing position).
   - If `sell_strength > buy_strength × 1.3` → `sell` (existing) or `wait` (no position).
   - Else → `wait` (no clear edge).
4. **Empty signal list** → `hold` if held, `wait` otherwise.

Confidence on signal-driven stances = average strength of the dominant direction's signals.

The 30% edge (×1.3 multiplier) prevents whipsawing on barely-leaning signal sets. Tunable; currently hard-coded.

Each stance's `rationale` lists 3 bullets quoting concrete numbers from the inputs (signal counts, sums, current price, recent interpretations) — never generic phrases.

### Task 3: Router

```python
@router.get("/{symbol}", response_model=TradeRecommendationView)
async def get_recommendation(
    session: SessionDep,
    symbol: str = Path(..., pattern=r"^[A-Za-z0-9.\-]{1,16}$"),
    broker_account_id: Optional[int] = None,
    range: str = "3mo",
) -> TradeRecommendationView:
```

`broker_account_id` is optional — without it, the service runs the same rule chain but skips the cost-basis-driven shortcuts.

### Task 4: Frontend card

`TradeRecommendationCard` color-codes the stance:
- `buy` / `tp_triggered`: green border + green icon (TrendingUp / Target)
- `sell` / `stop_triggered`: red border + red icon (TrendingDown / AlertTriangle)
- `hold` / `wait`: muted border + Pause icon

Position block (avg cost / shares / U-PnL / stop+TP) renders only when `has_position` is true.

Wired as the **first** child of `EquityResearchPage`'s Overview tab so the user sees the synthesized advice before the raw data.

### Task 5: Tests

Five fixture tests with `chart_service.get_symbol_chart` and `signals_service.compute_for_symbol` mocked via `unittest.mock.AsyncMock`:

1. Stop-loss triggered short-circuits other signals.
2. Take-profit triggered short-circuits.
3. Buy dominance with no position → "buy".
4. No signals → "wait" (no position) / "hold" (held).
5. Mixed signals (within 30% edge) → "wait".

Position rows are seeded via `position_costs_service.upsert(...)` in the same test fixture's tmp DB so no monkeypatching of the cost service is needed.

---

## Self-Review

- [x] Stop / TP rules are the highest priority and short-circuit before signal tally.
- [x] Confidence math has no division by zero (uses `max(buy_count, 1)` denominator).
- [x] Rationale always cites concrete numbers — never "momentum is strong" without an RSI value.
- [x] Recommendation generated_at is timezone-aware UTC.

## Concerns / Follow-ups

1. **30% edge multiplier is magic-number-tuned.** Consider exposing as a runtime_settings key for power users.
2. **No persistence.** Recommendations are computed on every request; we could cache for ~60s if traffic warrants.
3. **No AI Council overlay.** The rule-based path is deterministic; a future enhancement would call `agents_service.council` with 1-2 personas and surface their `verdict + action_plan` as a sibling stance.
4. **Trade-rec doesn't yet feed into auto-trading.** The user reads it, then clicks "Add buy" or sets stops manually. A future "execute this stance" button would close the loop.
5. **`recent_signals_count` is the total, not "in last N days".** A symbol with 50 signals over 3 months looks identical to 50 in the last week. Consider a recency-weighted score.
6. **Action chips use English literals on the wire** (`buy` / `sell`). Frontend i18n maps them to per-locale labels via the `ACTION_TONE` table — extend that map for locale parity.
