# TradingView pine-seeds Bridge

**Status:** Pending. To be executed via `/subagent-driven-development`.

**Goal:** Push selected Newbird-computed signals (GEX walls, valuation bands, macro ensemble levels) as historical CSV data to a **public GitHub repo** in TradingView's [pine-seeds](https://github.com/tradingview-pine-seeds) format, so a Pine Script indicator on TradingView can render them directly on a chart.

**Why this matters:** TradingView is the chart most retail/quant users actually look at. The native Newbird charts on `/news` and `/macro` are functional but limited. By exporting our computed levels (e.g. SPY's call wall at $720, NVDA's PE-p50 fair value at $148) as TradingView-loadable data, the user can overlay Newbird's analytics on their preferred charting tool without copy-pasting numbers.

---

## How pine-seeds works (background, 60-second version)

1. You publish a **public GitHub repo** with a fixed structure — TradingView pulls CSVs from it on a schedule (~ daily after EOD)
2. Each "ticker" is one CSV file at `data/<EXCHANGE>_<SYMBOL>, <RES>.csv` with `time,open,high,low,close,volume` columns (OHLCV; you can repurpose the columns to mean whatever you want — e.g. open=call_wall, close=put_wall)
3. A `symbol_info/` JSON file declares the symbol's metadata (description, name, currency, etc.)
4. A `seeds_categories.json` file at the root maps the user-friendly category to the symbol list
5. You apply for whitelisting via TradingView's form (one-time, async — takes 1-2 weeks)
6. While waiting, the data is private to your account but the bot runs every push

So the deliverable from Newbird's side is: **generate the right CSVs/JSON files in a local directory, optionally git-push them to the configured repo URL.**

---

## Architecture

```
                    ┌─────────────────────────────────┐
                    │  Newbird services               │
                    │  ─ options_chain_service        │
                    │  ─ valuation_service            │
                    │  ─ macro_service                │
                    └────────────────┬────────────────┘
                                     │ (current snapshots)
                                     ▼
              ┌───────────────────────────────────────────┐
              │  app/services/pine_seeds_service.py       │
              │   build_pine_seeds_payload(...)           │
              │     ├─ for each tracked symbol:           │
              │     │   → snapshot row with               │
              │     │     {time, call_wall, put_wall,     │
              │     │      max_pain, fair_p50}            │
              │     ├─ for macro ensemble:                │
              │     │   → one row per ensemble signal     │
              │     └─ append to CSV, idempotent          │
              └────────────────┬──────────────────────────┘
                               │
                               ▼
              ┌───────────────────────────────────────────┐
              │  Local pine-seeds workspace               │
              │  ${DATA_DIR}/pine_seeds/                  │
              │   ├─ data/                                │
              │   │   ├─ NEWBIRD_SPY_LEVELS, 1D.csv      │
              │   │   ├─ NEWBIRD_NVDA_LEVELS, 1D.csv     │
              │   │   └─ NEWBIRD_MACRO_ENSEMBLE, 1D.csv  │
              │   ├─ symbol_info/                         │
              │   │   ├─ NEWBIRD_SPY_LEVELS.json         │
              │   │   ├─ NEWBIRD_NVDA_LEVELS.json        │
              │   │   └─ NEWBIRD_MACRO_ENSEMBLE.json     │
              │   └─ seeds_categories.json                │
              └────────────────┬──────────────────────────┘
                               │ (optional)
                               ▼
              ┌───────────────────────────────────────────┐
              │  app/services/pine_seeds_publisher.py     │
              │   git add + commit + push                 │
              │   (only if PINE_SEEDS_REPO_URL is set)    │
              └───────────────────────────────────────────┘
```

---

## What gets exported (the Newbird → pine-seeds mapping)

We ship **3 ticker types**:

### 1. Per-symbol options levels — `NEWBIRD_<SYM>_LEVELS, 1D.csv`

For each symbol in the user's options watchlist (default `[SPY, QQQ, NVDA, AAPL]`):

| pine-seeds column | Newbird value | Meaning |
|---|---|---|
| `time` | UTC midnight of snapshot day | row key |
| `open` | call_wall | upside resistance level |
| `high` | put_wall | downside support level |
| `low` | max_pain | nearest-expiry max pain |
| `close` | zero_gamma | dealer gamma flip point |
| `volume` | total_chain_oi | scale of the GEX surface |

The Pine Script indicator just plots `open / high / low` as horizontal lines on the chart.

### 2. Per-symbol valuation bands — `NEWBIRD_<SYM>_VAL, 1D.csv`

Only for symbols with a valid PE channel:

| pine-seeds column | Newbird value |
|---|---|
| `time` | UTC midnight of snapshot day |
| `open` | fair_p25 |
| `high` | fair_p95 |
| `low` | fair_p5 |
| `close` | fair_p50 |
| `volume` | sample_size (years × 252) |

### 3. Macro ensemble — `NEWBIRD_MACRO_ENSEMBLE, 1D.csv`

One row per day capturing the ensemble health:

| pine-seeds column | Newbird value |
|---|---|
| `time` | UTC midnight of snapshot day |
| `open` | count of "ok" signals |
| `high` | count of "warn" signals |
| `low` | count of "danger" signals |
| `close` | count of "neutral" signals |
| `volume` | total_core (always = 4 right now) |

This lets the Pine Script user plot a regime-shift line on any chart.

---

## Out of scope (deliberate)

- **Real-time data** — pine-seeds is daily-EOD only. Intra-day GEX shifts won't be exported.
- **TradingView whitelist application** — that's a one-shot manual step the user does in the TV web UI; we just emit the right files.
- **Pine Script indicators themselves** — we publish 1 example `.pine` file under `pine/` for documentation, but writing a full Pine Script library is a separate task.
- **GitHub Actions / cron** — Newbird's existing FastAPI process runs the export when the API is hit; the user can wire a cron later if they want hourly.
- **Multi-account / multi-user** — single user, single repo.

---

## File structure

### New
| Path | Responsibility |
|---|---|
| `backend/core/pine_seeds/__init__.py` | Public API |
| `backend/core/pine_seeds/csv_builder.py` | `build_levels_row(...) → dict`, `build_val_row(...) → dict`, `build_macro_row(...) → dict` |
| `backend/core/pine_seeds/symbol_info.py` | `symbol_info_for(ticker, kind) → dict` (the `symbol_info/<X>.json` payload) |
| `backend/app/services/pine_seeds_service.py` | Orchestrates: pull current snapshots from existing services, append CSV rows, write symbol_info + categories |
| `backend/app/services/pine_seeds_publisher.py` | Optional `git add/commit/push` to `PINE_SEEDS_REPO_URL` |
| `backend/app/routers/pine_seeds.py` | 2 endpoints: status + manual trigger |
| `backend/app/models/pine_seeds.py` | Pydantic schemas |
| `backend/tests/test_pine_seeds_csv.py` | Unit tests for CSV row building (pure-python, no I/O) |
| `backend/tests/test_pine_seeds_service.py` | Service tests with mocked source services + tmp dir |
| `pine/example_levels.pine` | Documentation: an example Pine Script indicator that loads our data |

### Modified
| File | Change |
|---|---|
| `backend/app/runtime_settings.py` | Add `PINE_SEEDS_DIR`, `PINE_SEEDS_REPO_URL`, `PINE_SEEDS_WATCHLIST` |
| `backend/app/main.py` | Register `pine_seeds_router` |
| `backend/tests/test_openapi_parity.py` | Whitelist 2 new routes |
| `frontend-v2/src/pages/SettingsPage.jsx` | Add 3 settings to the existing OPTIONAL_KEYS list |
| `frontend-v2/src/i18n/locales/{en,zh,de,fr}.json` | Labels for 3 new settings |

---

## Pre-flight

- [ ] Branch from `feat/ibkr-broker`. New branch: `feat/tradingview` (already cut).
- [ ] Baseline pytest: ≥ 281 passing.
- [ ] No new dependencies — use stdlib `csv` + `subprocess` (for git push). `gitpython` is overkill.

---

## Task 1: CSV row builders (TDD pure-python)

**Files:**
- Create: `backend/core/pine_seeds/__init__.py`
- Create: `backend/core/pine_seeds/csv_builder.py`
- Create: `backend/core/pine_seeds/symbol_info.py`
- Create: `backend/tests/test_pine_seeds_csv.py`

**Spec:**

```python
# csv_builder.py

CSV_HEADER = ("time", "open", "high", "low", "close", "volume")

def build_levels_row(*, snapshot_date: date, gex_summary: dict) -> dict[str, str]:
    """One row for NEWBIRD_<SYM>_LEVELS. Maps gex_summary fields to OHLCV.
    Returns {"time": "<unix_seconds>", "open": "<call_wall>", ...}.
    NaN / None fields render as empty string (TradingView treats as gap)."""

def build_val_row(*, snapshot_date: date, pe_channel: dict) -> dict[str, str]:
    """One row for NEWBIRD_<SYM>_VAL. Maps PE-channel fields to OHLCV."""

def build_macro_row(*, snapshot_date: date, ensemble: dict) -> dict[str, str]:
    """One row for NEWBIRD_MACRO_ENSEMBLE. Maps signal counts to OHLCV."""

def append_csv_row(path: Path, row: dict[str, str], header: tuple[str, ...] = CSV_HEADER) -> bool:
    """Append a row to the CSV, creating the file with header if missing.
    Returns False (no-op) if a row with the same `time` already exists
    (idempotent — re-running a daily snapshot doesn't dupe). True if appended."""

# symbol_info.py

def symbol_info_for(ticker: str, kind: Literal['LEVELS','VAL','MACRO']) -> dict:
    """Returns the dict that gets serialized to symbol_info/<ticker>.json.
    Per pine-seeds spec:
        {"symbol": [<TICKER>], "description": [...], "currency": "USD",
         "session-regular": "0930-1600", "timezone": "America/New_York",
         "type": "indicator"}
    For MACRO and indicator-style tickers, type="indicator". For LEVELS/VAL,
    type="indicator" too (not "stock") because the OHLCV columns are signals,
    not real price."""
```

**Tests (write first):**
- `build_levels_row` from a known gex_summary returns the expected OHLCV values
- `build_levels_row` handles None call_wall (empty string in CSV)
- `build_val_row` handles a PE channel with all None bands (entire row is empty values except `time`)
- `build_macro_row` packs the 4 signal counts into OHLCV correctly
- `append_csv_row` creates file with header on first call
- `append_csv_row` is idempotent — second call with same `time` returns False, doesn't dupe
- `append_csv_row` accepts new dates and appends
- `symbol_info_for("SPY", "LEVELS")` returns the expected JSON-serializable dict
- `symbol_info_for` validates `kind` (raises ValueError for unknown)

**Acceptance:** All tests pass. Pytest 281 → 290 (9 new tests).

---

## Task 2: pine_seeds service (orchestration)

**Files:**
- Create: `backend/app/services/pine_seeds_service.py`
- Create: `backend/tests/test_pine_seeds_service.py`

**Spec:**

```python
async def export_snapshot(
    workspace: Path,
    *,
    symbols: list[str] | None = None,
    include_macro: bool = True,
) -> dict[str, Any]:
    """Build the full pine-seeds workspace under `workspace`.

    Args:
        workspace: target directory (will be created)
        symbols: list of tickers to export levels + val for. None → read
                 from PINE_SEEDS_WATCHLIST setting (CSV string), else
                 default ["SPY", "QQQ", "NVDA", "AAPL"]
        include_macro: also emit NEWBIRD_MACRO_ENSEMBLE

    Returns:
        {
            "workspace": str(workspace),
            "tickers_emitted": [...],
            "rows_written": int,
            "rows_skipped": int,
            "errors": [{"ticker": "...", "kind": "...", "error": "..."}],
        }

    Skips a (ticker, kind) silently if the underlying service raises (e.g.
    PE channel unavailable for a no-EPS stock). Logs but doesn't fail.
    """
```

The service:
1. Creates `workspace/data/` and `workspace/symbol_info/`
2. For each symbol:
   - Pull current GEX summary via `options_chain_service.get_gex_summary(sym)` → build levels row → append to `data/NEWBIRD_<SYM>_LEVELS, 1D.csv` + write `symbol_info/NEWBIRD_<SYM>_LEVELS.json` if missing
   - Pull current PE channel via `valuation_service.fetch_pe_channel(sym)` → if any band is non-None, build val row → append + write symbol_info
3. If `include_macro`: pull `macro_service.get_dashboard()` → build macro row → append to `data/NEWBIRD_MACRO_ENSEMBLE, 1D.csv` + write symbol_info
4. Write/update `seeds_categories.json` at workspace root with one category "Newbird Signals" listing all emitted tickers

**Tests (mock the 3 source services entirely):**
- Happy path: 2 symbols + macro → 5 CSV files (2 levels + 2 val + 1 macro) + 5 symbol_info JSONs + categories.json
- Idempotent: second call same day appends 0 rows
- A symbol with no PE data emits levels CSV but skips val CSV
- A symbol whose options chain raises emits 0 rows for that symbol but other symbols still process
- The error list contains the failed (ticker, kind) entries
- `symbols=None` reads `PINE_SEEDS_WATCHLIST` runtime setting, falls back to default if unset

**Acceptance:** Pytest 290 → 296 (6 new tests).

---

## Task 3: Optional git publisher

**Files:**
- Create: `backend/app/services/pine_seeds_publisher.py`
- Add tests to: `backend/tests/test_pine_seeds_service.py` (extend, no new file)

**Spec:**

```python
async def publish_workspace(workspace: Path) -> dict[str, Any]:
    """Commit + push the workspace to PINE_SEEDS_REPO_URL.

    If PINE_SEEDS_REPO_URL is not set: returns {"published": False, "reason": "not configured"}.
    If set but not a git repo yet: clone or init and add remote.
    If set and is a git repo: git add . / git commit / git push.

    All operations via subprocess.run([...], cwd=workspace, check=True).
    Catches CalledProcessError and returns {"published": False, "reason": "<stderr>"}.

    The commit message: "newbird snapshot {YYYY-MM-DD}".

    Authentication: assumes the user has a credential helper or SSH agent
    set up. We don't bake in tokens. If push fails because of auth, the
    error surfaces as the "reason" string and the user fixes it once.
    """
```

**Tests:**
- `PINE_SEEDS_REPO_URL` unset → returns `not configured`
- A real workspace with the right structure, mocked `subprocess.run` succeeds → returns `published=True`
- `subprocess.run` raises CalledProcessError → returns `published=False, reason=<stderr>`

(Use `unittest.mock.patch('subprocess.run')` — don't actually shell out in tests.)

**Acceptance:** Pytest 296 → 299 (3 new tests).

---

## Task 4: API router

**Files:**
- Create: `backend/app/routers/pine_seeds.py`
- Create: `backend/app/models/pine_seeds.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/main.py` — register router
- Modify: `backend/tests/test_openapi_parity.py` — whitelist 2 routes

**Spec:**

```python
class PineSeedsStatusResponse(BaseModel):
    workspace: str | None      # path to local workspace, None if not initialized
    repo_url: str | None       # PINE_SEEDS_REPO_URL, None if unset
    last_export_at: datetime | None
    tickers_emitted: list[str]

class PineSeedsExportRequest(BaseModel):
    symbols: list[str] | None = None
    include_macro: bool = True
    publish: bool = False      # if True, also git-push after building

class PineSeedsExportResponse(BaseModel):
    workspace: str
    tickers_emitted: list[str]
    rows_written: int
    rows_skipped: int
    errors: list[dict[str, str]]
    published: bool
    publish_reason: str | None
    generated_at: datetime
```

**Endpoints:**

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/pine-seeds/status` | — | `PineSeedsStatusResponse` |
| POST | `/api/pine-seeds/export` | `PineSeedsExportRequest` | `PineSeedsExportResponse` |

**Acceptance:** 2 new routes registered. Pytest 299 → at least 299 (no test count change strictly required — we covered service-level in Tasks 2 and 3).

---

## Task 5: Settings + i18n

**Files:**
- Modify: `backend/app/runtime_settings.py` — register 3 new settings
- Modify: `frontend-v2/src/pages/SettingsPage.jsx` — add 3 entries to OPTIONAL_KEYS
- Modify: `frontend-v2/src/i18n/locales/{en,zh,de,fr}.json` — labels + hints

3 settings, all `category="research"`, `required=False`, `sensitive=False`:

| Key | Default | Hint (en) |
|---|---|---|
| `PINE_SEEDS_DIR` | `""` | "Local directory where TradingView pine-seeds CSVs are written. Default: `${DATA_DIR}/pine_seeds`." |
| `PINE_SEEDS_REPO_URL` | `""` | "Public GitHub repo URL (HTTPS or SSH) for pine-seeds. Required only if you want auto-push. Apply for TradingView whitelist at https://github.com/tradingview-pine-seeds." |
| `PINE_SEEDS_WATCHLIST` | `"SPY,QQQ,NVDA,AAPL"` | "Comma-separated list of symbols to export options/valuation levels for." |

**Acceptance:** Settings page renders the 3 new keys in 4 languages. Frontend build clean.

---

## Task 6: Final verify + commit

- Full pytest: ≥ 299 passing (was 281, +18)
- Frontend build clean
- Live smoke (if backend is up):
  - GET `/api/pine-seeds/status` returns `{"workspace": null, ...}` on a fresh state
  - POST `/api/pine-seeds/export` with `{"publish": false}` writes files to a tmp dir; response shows `tickers_emitted` and `rows_written > 0`
  - Inspect a generated file: `cat ${DATA_DIR}/pine_seeds/data/NEWBIRD_SPY_LEVELS\,\ 1D.csv` shows `time,open,high,low,close,volume\n<unix>,<call_wall>,<put_wall>,<max_pain>,<zero_gamma>,<oi>`
- Commit: `chore(pine-seeds): final integration check`
- Branch ready to merge

---

## Done-criteria

- 6 logical commits on `feat/tradingview`
- pytest ≥ 299 passing
- 2 new routes (`/api/pine-seeds/status`, `/api/pine-seeds/export`)
- 3 new settings registered + rendered in Settings page (4 languages)
- A user with a public GitHub repo can:
  - Set `PINE_SEEDS_REPO_URL=https://github.com/<them>/pine-seeds` in Settings
  - POST `/api/pine-seeds/export` with `publish=true`
  - See the workspace pushed to GitHub
  - Apply for TradingView whitelist using that repo URL
  - Once whitelisted, see Newbird's signals as ticker symbols on TradingView (e.g. `NEWBIRD:SPY_LEVELS`)
- Without a `PINE_SEEDS_REPO_URL`, the export still works locally — files are written to disk and can be inspected manually

---

## Risks / open questions

1. **TradingView CSV format strictness:** pine-seeds uses a specific `time,open,high,low,close,volume` column order with unix-second timestamps. Implementer must adhere exactly; our `build_*_row` functions must produce strings, not floats (CSV expects literal text).
2. **Filename quoting:** pine-seeds wants files named like `EXCH_SYM, 1D.csv` — note the space after comma. Implementer must match this format including the space.
3. **Idempotency under day-boundary races:** if the export runs twice within a few minutes near UTC midnight, we might write two rows with different `time` values for what's logically the same day. Mitigation: snapshot date is always `date.today()` in UTC, then converted to unix-second of `00:00:00 UTC`. Idempotent dedup keys on that timestamp.
4. **Live `git push` is hard to test:** Task 3 mocks subprocess. Real-world breakage will only show when the user actually runs `publish=true`. Acceptable risk for v1.
