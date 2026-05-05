# Phase 3: Fundamentals + Alt-Data Panel

**Goal:** Multi-source factor inputs beyond OHLCV, raising real-world IC from
0.005-0.020 to 0.02-0.06+ on Alpaca daily panels by adding signal sources
WorldQuant Alpha 101 paper assumed but our current pipeline never touches.

**Scope:** ~1-2 days of work. Each section is independently shippable.

---

## What's Missing Today

`factor_daily_bars` only has `open / high / low / close / volume / vwap`.
`factor_symbol_meta` has `sector / industry / market_cap` but only the
LATEST snapshot, not a daily timeseries. The factor AST operators
reference `open / high / low / close / volume / vwap / returns` only.

Real systematic alpha typically draws from 4 additional families:

| Family | Examples | Predictive horizon |
|---|---|---|
| **Fundamentals** | PE, PB, EPS growth, FCF yield, ROE, debt/equity | 20-60d |
| **Quality / Profitability** | Gross margin, asset turnover, FCF stability | 20-60d |
| **Sentiment** | News tone, social volume, analyst revisions | 1-10d |
| **Microstructure** | Short interest %, options skew, days-to-cover | 5-20d |

---

## Plan (4 sub-tasks)

### Sub-task 3.1: Fundamentals time-series table (~3h)

**Problem:** `factor_symbol_meta.market_cap` is a single point-in-time value.
For backtesting we need the historical value at each date.

**Files:**
- Create: `backend/app/db/tables.py` — append `FactorDailyFundamentals` table
- Create: `backend/app/services/factor_fundamentals_service.py`
- Modify: `backend/app/services/factor_pipeline.py::daily_data_refresh` — add
  fundamentals refresh step

**Schema:**
```python
class FactorDailyFundamentals(Base):
    __tablename__ = "factor_daily_fundamentals"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    market_cap: Mapped[float | None]
    pe_ratio: Mapped[float | None]
    pb_ratio: Mapped[float | None]
    eps_ttm: Mapped[float | None]
    revenue_ttm: Mapped[float | None]
    gross_margin: Mapped[float | None]
    debt_to_equity: Mapped[float | None]
    roe: Mapped[float | None]
    short_interest_pct: Mapped[float | None]
```

**Source:** Polygon Reference + Financials API (we have `POLYGON_API_KEY`).
- `GET /v3/reference/tickers/{symbol}` → snapshot
- `GET /vX/reference/financials?ticker=X&filing_date.gte=Y` → quarterly
  point-in-time data

**Strategy:** Forward-fill quarterly data into daily rows (a fundamental
known after filing date Y is the assumption for every date ≥ Y).

**Validation:** `POST /admin/refresh-fundamentals?days=30` — backfill last
30 days for the active universe (100 symbols). Single fundamental snapshot
should populate ~3000 daily rows (100 × 30).

### Sub-task 3.2: Augment panel + AST operators (~2h)

**Files:**
- Modify: `backend/app/services/factor_data_service.py::get_panel` —
  left-join on `factor_daily_fundamentals` so panel has new columns
- Modify: `backend/core/factors/ast.py` and `core/factors/eval.py` — register
  the new column names as valid leaf operators

**New leaf names available to GP:**
`market_cap` `pe` `pb` `eps_growth` `fcf_yield` `roe` `gm` `de` `si_pct`

**Existing operators (`rank`, `ts_mean`, `correlation`, etc.) automatically
work** on these new leaves once `eval.py` accepts them as panel columns.

**Validation:** New AST formula `rank(div(eps_ttm, market_cap))` should
parse, evaluate, and produce a non-empty score series.

### Sub-task 3.3: News sentiment daily aggregate (~3h)

**Problem:** `factor_news_features` table exists but is per-headline. Need
a per-(symbol, date) aggregate to feed factor formulas.

**Files:**
- Modify: `backend/app/db/tables.py::DailyNewsFeatures` — confirm schema
  (may already aggregate)
- Create: `backend/app/services/factor_sentiment_service.py` —
  daily news → sentiment_score / news_volume / sentiment_momentum_5d
- Modify: `factor_pipeline.daily_data_refresh` — call sentiment refresh

**Aggregations per (symbol, date):**
- `news_count` = number of headlines that day
- `sentiment_mean` = mean tone (-1 to +1)
- `sentiment_volatility` = std of tone within day
- `sentiment_5d_change` = sentiment_mean[t] - sentiment_mean[t-5]

**Source:** existing `tavily_service` cached headlines + OpenAI scoring
(already happens via `news_clustering`). New service joins existing tables.

**New leaf names:** `news_count` `news_sent` `news_sent_vol` `news_sent_chg`

### Sub-task 3.4: Options-derived signals (~2h, optional)

**Problem:** Options chain has predictive info (skew, GEX, IV rank) we
already compute for the Options page but don't feed to factor mining.

**Files:**
- Create: `backend/app/services/factor_options_features_service.py` —
  daily snapshot of (symbol, date) → iv_rank, put_call_oi, gex_pressure
- Add: `backend/app/db/tables.py::FactorDailyOptionsFeatures`

**Aggregations per (symbol, date):**
- `iv_rank` — 1y percentile of ATM IV
- `put_call_oi_ratio`
- `gex_pressure` (current GEX / market_cap)
- `option_skew_25d` (25-delta put IV - 25-delta call IV)

**Source:** existing `options_chain_service` already computes these for
the GEX endpoints. Just persist a daily snapshot for top-200 symbols.

**Caveat:** yfinance options data is slow — capping at top-200 keeps the
refresh under 5 min.

**New leaf names:** `iv_rank` `pc_oi` `gex_press` `skew_25d`

---

## Sequencing

Each sub-task is independent except:
- 3.2 depends on 3.1 (need data before exposing it to AST)
- All others can ship independently

**Recommended order:** 3.1 → 3.2 (combined deploy) → 3.3 → 3.4

---

## Expected Quality Lift

Empirical priors from quant literature:

| Factor family | Typical IC on US large-cap daily | Compounding |
|---|---|---|
| OHLCV-only (current) | 0.005-0.020 | baseline |
| + fundamentals | +0.005-0.015 | combine via fitness ensemble |
| + sentiment | +0.003-0.010 | |
| + options skew | +0.002-0.008 | |

After all four families, **best ensemble factor** typically lands at
IC=0.03-0.06, which is the WorldQuant paper's "good Alpha" tier.

**The one factor we'd never beat without 3.1:** `rank(neg(pb))` —
straight value factor. On any 4y US equity panel it produces IC ≈ 0.02-0.04.
Currently impossible to express because `pb` doesn't exist as a panel column.

---

## Out of Scope

- **Intraday data**: would 10× storage and complicate pipeline; keep daily
- **Macro overlays** (rates, credit spreads): possible later via FRED API
- **Industry classification refinement**: GICS already in SymbolMeta is fine
- **Options open interest cross-section** at strike level: too sparse

---

## Greenlight checklist

Before starting, confirm:
- [ ] Polygon plan supports `/vX/reference/financials` (free tier may not)
- [ ] yfinance is acceptable as fallback for fundamentals
- [ ] OK to add ~50K rows/day to SQLite (~10MB/year)
- [ ] OK to spend ~5 min/day on options features refresh

If Polygon free tier blocks 3.1, fallback chain:
yfinance.Ticker.info → SimFin → Stooq → manual backfill from quarterly 10-Q.
