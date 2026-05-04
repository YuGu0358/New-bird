# skfolio Adapter — Optional Second Optimizer Backend

> **Retroactive plan.** This document describes a feature that has already shipped on `feat/portfolio-opt` as commit `71ca313` (`feat(portfolio-opt): optional skfolio backend (HRP, mean-risk)`). It is reverse-engineered from the actual diff so future contributors who want to add another optimizer backend (riskfolio-lib, vnpy, custom) can read a plan-shaped doc rather than a raw diff. The "tasks" describe what was done in the order it should be re-done if someone needed to redo the work.

> **For agentic workers:** this plan is documentation-first. The implementation already exists; do **not** re-run the edits. Use this file as a reference for the design choices that landed and the points of extension.

---

## Goal

Borrow the idea behind FinceptTerminal's `scripts/Analytics/skfolio_wrapper` by adding [skfolio](https://github.com/skfolio/skfolio) as an **opt-in second optimizer backend** alongside the existing PyPortfolioOpt path. skfolio offers Hierarchical Risk Parity (HRP), Nested Cluster Optimization (NCO), Mean-Risk with modern numerics, and robust covariance models — none of which PyPortfolioOpt exposes.

Concrete requirements for the shipped change:

- A new request field `backend: "pyportfolioopt" | "skfolio"` on `/api/portfolio/optimize` (default `pyportfolioopt`).
- A new mode `hrp` (Hierarchical Risk Parity) that is only valid when `backend="skfolio"`.
- Lazy import: users who never request `backend="skfolio"` see no behavior change and do not need skfolio installed.
- The response envelope carries a `backend` field so the UI knows which path produced the weights.
- skfolio is **not** added to `requirements.txt` — it pulls scikit-learn + cvxpy and is heavy. Users opt in by `pip install skfolio`.

---

## Architecture (capture the actual decisions)

The shipped design is intentionally narrow. Capture it before extending.

1. **Adapter module, not a strategy class.** The new code lives in a single file `backend/core/portfolio_opt/skfolio_adapter.py` that exposes `is_available()` and `optimise(prices, *, mode, risk_free_rate)`. It mirrors the shape of `core.portfolio_opt.optimizer.OptimizationResult` so the service layer can treat the two paths uniformly. No abstract base class, no registry — KISS / YAGNI. If a third backend lands, that's the moment to extract a Protocol; until then, two `if backend == "x"` branches in the service is fine.

2. **Lazy import inside `optimise()`.** The actual `from skfolio.optimization import …` lives inside the function body, not at module top-level. `is_available()` exists as a probe so callers can detect installation status without raising. Rationale: the rest of NewBird must keep working when skfolio isn't installed. Importing at module top would break `from core.portfolio_opt.skfolio_adapter import …` for every user.

3. **skfolio NOT added to `requirements.txt`.** It transitively pulls scikit-learn + cvxpy, which roughly doubles the wheel surface and adds OS-level BLAS requirements. Users who want it run `pip install skfolio`. The error message when missing is explicit:
   ```
   skfolio not installed. Run `pip install skfolio` to enable this backend.
   ```

4. **`mode` literal extended with `"hrp"`.** HRP is specific to skfolio (PyPortfolioOpt has no HRP equivalent in our wrapper). The `ModeLiteral` in `app/models/portfolio_opt.py` becomes `Literal["max_sharpe", "min_volatility", "efficient_return", "hrp"]` — one literal, both backends, with the service layer rejecting illegal combinations:
   - `pyportfolioopt` rejects `"hrp"`.
   - `skfolio` rejects `"min_volatility"` and `"efficient_return"`; accepts `"max_sharpe"`, `"mean_risk"`, `"hrp"` and maps `"max_sharpe"` → skfolio's `MeanRisk` (which maximises Sharpe by default).

5. **Response carries `backend`.** `PortfolioOptimizeResponse.backend` is a plain `str` (default `"pyportfolioopt"`) so the UI can render which optimizer produced the weights. Not a `Literal` on the response side — keeps it forward-compatible if a third backend lands.

6. **Mean-Risk mapping is intentional.** When the user asks for `mode="max_sharpe"` against the skfolio backend, the adapter quietly maps to `mean_risk` (skfolio's `MeanRisk` model maximises Sharpe by default with the given `risk_free_rate`). The literal `"mean_risk"` is also accepted directly by the service. This keeps the front-end mode picker consistent across backends.

7. **HRP returns zero stats when skfolio raises.** `HierarchicalRiskParity` doesn't always expose `mean` / `standard_deviation` cleanly on the predicted portfolio. The adapter wraps the stats extraction in `try/except` and returns `0.0` for `expected_return`, `expected_volatility`, `sharpe_ratio` when the lookup fails. UI must tolerate zero-valued performance fields when `mode == "hrp"`.

8. **Reused infrastructure.** `run_sync_with_retries` (already used for the yfinance download and the PyPortfolioOpt call) wraps the skfolio call too — keeps the optimisation off the event loop and gets retry semantics for free.

---

## Tech Stack

- **Optional**: `skfolio>=0.5` (transitively pulls `scikit-learn`, `cvxpy`, `pandas`).
- **Already installed**: `pandas`, `pydantic` v2, `fastapi`.
- No new entries in `backend/requirements.txt` — that's the whole point.

---

## File Structure

**Created:**
- `backend/core/portfolio_opt/skfolio_adapter.py` — new adapter module (104 lines).

**Modified:**
- `backend/app/models/portfolio_opt.py` — extended `ModeLiteral`, added `BackendLiteral`, added `backend` field on request + response.
- `backend/app/services/portfolio_opt_service.py` — added `backend` parameter, branches on `backend == "skfolio"` after the yfinance download.
- `backend/app/routers/portfolio_opt.py` — passes `request.backend` through to the service.

**Not touched (deliberate):**
- `backend/core/portfolio_opt/__init__.py` — the new adapter is *not* re-exported there. Callers that want it must `from core.portfolio_opt.skfolio_adapter import …` explicitly. This keeps the package's default surface lean and keeps users without skfolio from accidentally triggering an import path that would fail.
- `backend/requirements.txt` — see "Architecture" point 3.

---

## Reference: Existing Code to Read Before Starting

If someone needed to redo this work (or wanted to add a third backend), they should read these files first:

1. `backend/core/portfolio_opt/optimizer.py` — the shape that the new adapter mirrors. Note: returns a frozen-ish dataclass with `weights`, `expected_return`, `expected_volatility`, `sharpe_ratio`.
2. `backend/app/services/portfolio_opt_service.py` — see how `_download_blocking` and the existing PyPortfolioOpt call are dispatched via `run_sync_with_retries`. The new branch follows the same pattern.
3. `backend/app/services/network_utils.py` — `run_sync_with_retries` is the wrapper used by both branches; understand its retry semantics before adding a third path.
4. `backend/app/models/portfolio_opt.py` — pydantic v2 patterns used across the codebase (`Field(default=…, ge=…, le=…)`, `Optional[…]`, `Literal[…]`).
5. FinceptTerminal's `scripts/Analytics/skfolio_wrapper` — the upstream inspiration. We borrow the *idea* (a skinny wrapper that exposes a small subset of skfolio modes) but not the code; license compatibility wasn't audited and the FinceptTerminal wrapper carries baggage we don't need.
6. skfolio docs at https://skfolio.org/ — specifically `MeanRisk`, `HierarchicalRiskParity`, and `prices_to_returns`. These are the only three symbols the adapter touches.

---

## Tasks

> Each task copies the **actual** shipped file content. If you find yourself editing these snippets to be "cleaner", stop — the intent of this doc is to capture what landed, not what could have landed.

### Task 1: Define the skfolio adapter module

**Files:**
- Create: `backend/core/portfolio_opt/skfolio_adapter.py`

- [ ] **Step 1: Confirm the optimizer dataclass shape we're mirroring**

```bash
grep -n "class OptimizationResult" /Users/yugu/NewBirdClaude/backend/core/portfolio_opt/optimizer.py
```

Expected: a `@dataclass` with `weights: dict[str, float]`, `expected_return: float`, `expected_volatility: float`, `sharpe_ratio: float`. The new adapter must produce the same fields so the service layer can build a uniform response envelope.

- [ ] **Step 2: Create the adapter file**

Write this exact content to `backend/core/portfolio_opt/skfolio_adapter.py`:

```python
"""skfolio backend for portfolio optimisation — borrowed from FinceptTerminal.

Optional: only used when ``backend="skfolio"`` is requested. Lazy-imports
the package so the rest of NewBird keeps working even when skfolio
isn't installed. skfolio offers HRP / NCO / Mean-Risk / robust covariance
models that PyPortfolioOpt doesn't expose; we surface a small subset
here and let users pull the rest by installing skfolio themselves.

Install: ``pip install skfolio`` (note: pulls scikit-learn, cvxpy).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd


SkfolioMode = Literal["mean_risk", "hrp"]


@dataclass(frozen=True)
class SkfolioResult:
    """Same shape as core.portfolio_opt.optimizer.OptimizationResult."""

    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    backend: str = "skfolio"


def is_available() -> bool:
    """True when skfolio can be imported."""
    try:
        import skfolio  # noqa: F401
        return True
    except Exception:
        return False


def optimise(
    prices: pd.DataFrame,
    *,
    mode: SkfolioMode = "mean_risk",
    risk_free_rate: float = 0.04,
) -> SkfolioResult:
    """Run a skfolio optimisation.

    Modes:
    - ``mean_risk``: skfolio.optimization.MeanRisk (~ Markowitz with
      modern numerics). Maximises Sharpe by default.
    - ``hrp``: Hierarchical Risk Parity (López de Prado). No expected
      return / Sharpe forecast — those fields are returned as 0.

    Raises:
        RuntimeError when skfolio isn't installed.
        ValueError on bad input.
    """
    if prices is None or prices.empty:
        raise ValueError("prices DataFrame is empty")

    try:
        from skfolio.optimization import MeanRisk, HierarchicalRiskParity
        from skfolio.preprocessing import prices_to_returns
    except Exception as exc:  # pragma: no cover — environment-dependent
        raise RuntimeError(
            "skfolio not installed. Run `pip install skfolio` to enable this backend."
        ) from exc

    returns = prices_to_returns(prices)

    if mode == "mean_risk":
        model = MeanRisk(risk_free_rate=risk_free_rate)
    elif mode == "hrp":
        model = HierarchicalRiskParity()
    else:
        raise ValueError(f"unknown skfolio mode {mode!r}")

    portfolio = model.fit_predict(returns)

    weights = {
        str(name): float(w)
        for name, w in zip(portfolio.assets, portfolio.weights)
        if abs(float(w)) > 1e-6
    }

    # skfolio.Portfolio exposes annualized stats.
    try:
        ann_return = float(portfolio.mean) * 252
        ann_vol = float(portfolio.standard_deviation) * (252 ** 0.5)
        sharpe = (ann_return - risk_free_rate) / ann_vol if ann_vol > 0 else 0.0
    except Exception:
        ann_return = 0.0
        ann_vol = 0.0
        sharpe = 0.0

    return SkfolioResult(
        weights=weights,
        expected_return=ann_return,
        expected_volatility=ann_vol,
        sharpe_ratio=sharpe,
    )
```

- [ ] **Step 3: Probe `is_available()` end-to-end**

```bash
cd /Users/yugu/NewBirdClaude/backend
source .venv/bin/activate
python -c "from core.portfolio_opt.skfolio_adapter import is_available; print('skfolio_available:', is_available())"
```

Expected: prints `skfolio_available: True` if installed, `False` otherwise. Either result is acceptable — the point is that no `ImportError` propagates.

- [ ] **Step 4: Confirm the adapter does NOT export from the package `__init__`**

```bash
grep -n "skfolio" /Users/yugu/NewBirdClaude/backend/core/portfolio_opt/__init__.py || echo "OK — not re-exported"
```

Expected: `OK — not re-exported`. Callers must import it via the explicit submodule path (`from core.portfolio_opt.skfolio_adapter import …`). This is intentional (Architecture point 8 above).

- [ ] **Step 5: Commit (this would be the first commit if redone, but the shipped code is one combined commit)**

```bash
git add backend/core/portfolio_opt/skfolio_adapter.py
git commit -m "feat(portfolio-opt): skfolio adapter with lazy import + is_available probe"
```

---

### Task 2: Extend pydantic models with `backend` field and `hrp` mode

**Files:**
- Modify: `backend/app/models/portfolio_opt.py`

- [ ] **Step 1: Read the existing model to confirm the starting shape**

```bash
cat /Users/yugu/NewBirdClaude/backend/app/models/portfolio_opt.py
```

Expected: a `ModeLiteral = Literal["max_sharpe", "min_volatility", "efficient_return"]` and a `PortfolioOptimizeRequest` / `PortfolioOptimizeResponse` pair with no `backend` field.

- [ ] **Step 2: Replace the file with the shipped version**

```python
"""Pydantic schema for /api/portfolio/optimize."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


ModeLiteral = Literal["max_sharpe", "min_volatility", "efficient_return", "hrp"]
BackendLiteral = Literal["pyportfolioopt", "skfolio"]


class PortfolioOptimizeRequest(BaseModel):
    tickers: list[str] = Field(min_length=2)
    lookback_days: int = Field(default=252, ge=21, le=2520)
    mode: ModeLiteral = "max_sharpe"
    target_return: Optional[float] = None
    risk_free_rate: float = Field(default=0.04, ge=0.0, le=0.5)
    # Optional: switch from PyPortfolioOpt (default) to skfolio (HRP, robust covariance, …)
    backend: BackendLiteral = "pyportfolioopt"


class PortfolioOptimizeResponse(BaseModel):
    tickers: list[str]
    lookback_days: int
    mode: str
    target_return: Optional[float] = None
    risk_free_rate: float
    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    backend: str = "pyportfolioopt"
    as_of: datetime
```

Key changes vs. before:
- `ModeLiteral` gained `"hrp"`.
- New `BackendLiteral = Literal["pyportfolioopt", "skfolio"]`.
- `PortfolioOptimizeRequest.backend: BackendLiteral = "pyportfolioopt"` — typed as `BackendLiteral` so an unknown backend name is rejected by pydantic before reaching the service.
- `PortfolioOptimizeResponse.backend: str = "pyportfolioopt"` — typed as plain `str` for forward compatibility (Architecture point 5).

- [ ] **Step 3: Verify import**

```bash
cd /Users/yugu/NewBirdClaude/backend
python -c "from app.models.portfolio_opt import PortfolioOptimizeRequest, PortfolioOptimizeResponse, ModeLiteral, BackendLiteral; print('OK')"
```

Expected: `OK`.

- [ ] **Step 4: Commit (folded into the single shipped commit if redone in one shot)**

```bash
git add backend/app/models/portfolio_opt.py
git commit -m "feat(portfolio-opt): pydantic models — backend literal + hrp mode"
```

---

### Task 3: Branch the service on `backend`

**Files:**
- Modify: `backend/app/services/portfolio_opt_service.py`

- [ ] **Step 1: Review the existing file**

```bash
grep -n "def run_optimization" /Users/yugu/NewBirdClaude/backend/app/services/portfolio_opt_service.py
```

Expected: a single async function `run_optimization(*, tickers, lookback_days, mode, target_return, risk_free_rate)` with no `backend` parameter.

- [ ] **Step 2: Replace `run_optimization` with the branched version**

The shipped function:

```python
async def run_optimization(
    *,
    tickers: list[str],
    lookback_days: int = 252,
    mode: str = "max_sharpe",
    target_return: float | None = None,
    risk_free_rate: float = 0.04,
    backend: str = "pyportfolioopt",
) -> dict[str, Any]:
    """High-level entry point.

    Raises:
        ValueError on bad inputs / optimisation failure.
        RuntimeError when yfinance returns no data, or when skfolio
        backend is requested but the package isn't installed.
    """
    if not tickers:
        raise ValueError("tickers is required")
    if len(tickers) < 2:
        raise ValueError("at least 2 tickers required")
    if backend not in {"pyportfolioopt", "skfolio"}:
        raise ValueError(f"backend must be 'pyportfolioopt' or 'skfolio', got {backend!r}")
    if backend == "pyportfolioopt" and mode not in SUPPORTED_MODES:
        raise ValueError(
            f"PyPortfolioOpt mode must be one of {SUPPORTED_MODES!r}, got {mode!r}"
        )
    if backend == "skfolio" and mode not in {"max_sharpe", "mean_risk", "hrp"}:
        raise ValueError(
            f"skfolio mode must be one of mean_risk/max_sharpe/hrp, got {mode!r}"
        )

    normalized = [str(t).strip().upper() for t in tickers if str(t).strip()]
    if len(normalized) < 2:
        raise ValueError("at least 2 valid tickers required after normalisation")

    prices = await run_sync_with_retries(_download_blocking, normalized, lookback_days)
    if prices.empty:
        raise RuntimeError("yfinance returned no price data for the requested tickers")

    if backend == "skfolio":
        from core.portfolio_opt.skfolio_adapter import optimise as sk_optimise
        sk_mode = "hrp" if mode == "hrp" else "mean_risk"
        sk_result = await run_sync_with_retries(
            sk_optimise, prices, mode=sk_mode, risk_free_rate=risk_free_rate,
        )
        return {
            "tickers": normalized,
            "lookback_days": lookback_days,
            "mode": mode,
            "target_return": target_return,
            "risk_free_rate": risk_free_rate,
            "weights": sk_result.weights,
            "expected_return": sk_result.expected_return,
            "expected_volatility": sk_result.expected_volatility,
            "sharpe_ratio": sk_result.sharpe_ratio,
            "backend": "skfolio",
            "as_of": datetime.now(timezone.utc),
        }

    result = optimise(
        prices,
        mode=mode,  # type: ignore[arg-type]
        target_return=target_return,
        risk_free_rate=risk_free_rate,
    )

    return {
        "tickers": normalized,
        "lookback_days": lookback_days,
        "mode": mode,
        "target_return": target_return,
        "risk_free_rate": risk_free_rate,
        "weights": result.weights,
        "expected_return": result.expected_return,
        "expected_volatility": result.expected_volatility,
        "sharpe_ratio": result.sharpe_ratio,
        "backend": "pyportfolioopt",
        "as_of": datetime.now(timezone.utc),
    }
```

Key behaviours to notice:

1. **The lazy import lives in the service too.** `from core.portfolio_opt.skfolio_adapter import optimise as sk_optimise` is inside the `if backend == "skfolio":` branch. Even though the adapter module *itself* is import-safe, putting the import here keeps the call site grep-able ("where do we touch skfolio?").
2. **Mode mapping happens at the boundary.** `sk_mode = "hrp" if mode == "hrp" else "mean_risk"` is a one-liner — `"max_sharpe"` and `"mean_risk"` both collapse to `"mean_risk"` for the adapter. The user-facing `mode` is preserved verbatim in the response so the UI can echo it back.
3. **Both branches go through `run_sync_with_retries`.** Don't be tempted to call `sk_optimise` directly from the async function — skfolio's `fit_predict` is CPU-bound and blocks the event loop.
4. **Validation per backend.** `pyportfolioopt` rejects `"hrp"`; `skfolio` rejects `"min_volatility"` and `"efficient_return"`. The order matters — backend check first, then mode check (so the error message is specific to the user's chosen backend).

- [ ] **Step 3: Sanity-check imports unchanged**

The top of `portfolio_opt_service.py` still reads:

```python
from app.services.network_utils import run_sync_with_retries
from core.portfolio_opt import SUPPORTED_MODES, optimise
```

i.e. only the existing `optimise` (PyPortfolioOpt) is imported at module top. `sk_optimise` is imported inside the branch.

- [ ] **Step 4: Commit (folded if redoing in one shot)**

```bash
git add backend/app/services/portfolio_opt_service.py
git commit -m "feat(portfolio-opt): service branches on backend with per-backend mode validation"
```

---

### Task 4: Pass `backend` through the router

**Files:**
- Modify: `backend/app/routers/portfolio_opt.py`

- [ ] **Step 1: Add `backend=request.backend` to the service call**

The whole router file is short. The only change is one new keyword argument inside the `try` block:

```python
@router.post("/optimize", response_model=PortfolioOptimizeResponse)
async def optimize_portfolio(
    request: PortfolioOptimizeRequest,
) -> PortfolioOptimizeResponse:
    """Mean-variance portfolio optimisation across the supplied tickers.

    Modes:
    - `max_sharpe`: maximise Sharpe ratio at the given risk-free rate.
    - `min_volatility`: minimise portfolio volatility.
    - `efficient_return`: minimise volatility subject to `target_return`.
    """
    try:
        payload = await portfolio_opt_service.run_optimization(
            tickers=request.tickers,
            lookback_days=request.lookback_days,
            mode=request.mode,
            target_return=request.target_return,
            risk_free_rate=request.risk_free_rate,
            backend=request.backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # No upstream data — degrade to 503 so the UI can show a "try
        # again later" instead of a generic 500.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PortfolioOptimizeResponse(**payload)
```

The diff is one new line: `backend=request.backend,`.

Notice the docstring still describes only the three PyPortfolioOpt modes — see Self-Review for why this is a follow-up, not a bug.

- [ ] **Step 2: Manual smoke check (skip if skfolio not installed)**

```bash
cd /Users/yugu/NewBirdClaude/backend
source .venv/bin/activate
uvicorn app.main:app --port 8000 &
sleep 2
curl -s -X POST http://127.0.0.1:8000/api/portfolio/optimize \
  -H 'Content-Type: application/json' \
  -d '{"tickers":["AAPL","MSFT","NVDA","GOOG"],"backend":"skfolio","mode":"hrp","lookback_days":252}' | jq .
kill %1
```

Expected when skfolio is installed: HTTP 200, `weights`, and `"backend": "skfolio"` in the body.
Expected when skfolio is NOT installed: HTTP 500 with the message `skfolio not installed. Run \`pip install skfolio\`…` (the `RuntimeError` from the adapter is caught by the catch-all `except Exception` → `service_error`).

- [ ] **Step 3: Confirm `backend="pyportfolioopt"` (default) is unchanged**

```bash
curl -s -X POST http://127.0.0.1:8000/api/portfolio/optimize \
  -H 'Content-Type: application/json' \
  -d '{"tickers":["AAPL","MSFT","NVDA","GOOG"],"mode":"max_sharpe","lookback_days":252}' | jq '.backend'
```

Expected: `"pyportfolioopt"`.

- [ ] **Step 4: Commit (folded)**

```bash
git add backend/app/routers/portfolio_opt.py
git commit -m "feat(portfolio-opt): router passes backend through"
```

---

### Task 5: Final verification + the actual shipped commit

In the actual shipped repo, the four steps above were squashed into a single commit (`71ca313`). If redoing the work end-to-end, the commit message that landed is:

```
feat(portfolio-opt): optional skfolio backend (HRP, mean-risk)
```

- [ ] **Step 1: Backend test suite passes (no new tests were added in this commit)**

```bash
cd /Users/yugu/NewBirdClaude/backend
source .venv/bin/activate
python -m pytest -q
```

Expected: pre-existing portfolio-opt tests still green. The shipped commit did **not** add tests for the skfolio path — see Self-Review for why this is flagged.

- [ ] **Step 2: OpenAPI shape**

```bash
curl -s http://127.0.0.1:8000/openapi.json | jq '.components.schemas.PortfolioOptimizeRequest.properties.backend'
```

Expected:

```json
{
  "enum": ["pyportfolioopt", "skfolio"],
  "default": "pyportfolioopt",
  "type": "string",
  "title": "Backend"
}
```

- [ ] **Step 3: Frontend build (the request body shape change is additive — `backend` is optional with a default, so existing callers don't break)**

```bash
cd /Users/yugu/NewBirdClaude/frontend-v2
npm run build 2>&1 | tail -8
```

Expected: clean build, no API client changes required.

- [ ] **Step 4: Single commit (the actual shipped form)**

```bash
git add backend/core/portfolio_opt/skfolio_adapter.py \
        backend/app/models/portfolio_opt.py \
        backend/app/services/portfolio_opt_service.py \
        backend/app/routers/portfolio_opt.py
git commit -m "feat(portfolio-opt): optional skfolio backend (HRP, mean-risk)"
```

---

## Self-Review Checklist

Run through this list to catch a regression if anyone touches the adapter or its callers.

### Behaviour preserved

- [ ] `backend` defaults to `"pyportfolioopt"` on the request — existing clients that don't send the field continue to hit the original path.
- [ ] `backend` defaults to `"pyportfolioopt"` on the response — `PortfolioOptimizeResponse` still validates against legacy responses where the field was missing.
- [ ] `pyportfolioopt` still rejects `"hrp"` (the new mode would reach `EfficientFrontier` and explode otherwise).
- [ ] `skfolio` still rejects `"min_volatility"` and `"efficient_return"` (those modes are PyPortfolioOpt-specific in this codebase).

### Lazy-import discipline

- [ ] `skfolio` is **not** imported at the top of `skfolio_adapter.py` — only inside `optimise()`.
- [ ] `is_available()` swallows *any* exception from the import, not just `ImportError` — distros like Apple Silicon can throw OS-level errors before `ImportError` if the cvxpy wheel is broken.
- [ ] `core/portfolio_opt/__init__.py` does **not** re-export the adapter (that would defeat the lazy-import).

### Mode mapping

- [ ] `mode="max_sharpe"` against the skfolio backend is mapped to skfolio's `mean_risk` (skfolio's MeanRisk maximises Sharpe by default).
- [ ] `mode="hrp"` is the only path that reaches `HierarchicalRiskParity()`.
- [ ] The user's original `mode` string is echoed verbatim in the response — the mapping is internal.

### Concerns / things that LOOK broken

These are flagged so the next contributor doesn't have to re-discover them.

1. **No tests for the skfolio path.** The shipped commit added zero tests for the new branch. The PyPortfolioOpt path has tests; the skfolio path has none, not even a `is_available()`-gated one with `pytest.importorskip("skfolio")`. When adding the next backend, write the test first (TDD) and consider backfilling at least one happy-path test for the skfolio branch.

2. **Router docstring is stale.** `optimize_portfolio` still documents only `max_sharpe` / `min_volatility` / `efficient_return`. It should also mention `hrp` and the `backend` parameter. Minor — purely a docs fix — but every contributor who reads the OpenAPI summary sees the stale text.

3. **`RuntimeError` from missing skfolio gets swallowed.** In `optimize_portfolio`, the explicit `except RuntimeError` branch maps to **HTTP 503** (intended for "yfinance has no data"). When skfolio is missing, the adapter raises `RuntimeError("skfolio not installed. …")` — which is *also* caught by that branch and surfaces as a 503 to the UI. That's misleading: 503 implies "transient, retry later", but the real cause is permanent (package missing). Consider a custom `BackendUnavailableError` or a 501 Not Implemented for this case. Worth a small follow-up.

4. **`prices` validation is duplicated.** `optimizer.optimise` does its own forward-fill / column drop before computing returns. `skfolio_adapter.optimise` just hands the raw frame to `prices_to_returns` and trusts skfolio to handle NaNs. If yfinance returns a frame with one ticker that's all-NaN, the two paths will fail differently (PyPortfolioOpt raises `ValueError`; skfolio may raise from inside scikit-learn). Not a bug per se, but the error surface isn't uniform.

5. **HRP stats fallback hides solver failures.** The adapter wraps `portfolio.mean` / `portfolio.standard_deviation` access in a bare `except Exception:` and returns `0.0`. If skfolio changes its API and that attribute lookup starts failing, the adapter will silently return `expected_return=0`, `sharpe=0`. Better: log the exception at WARNING level so the failure is visible during operation.

6. **`SkfolioResult.backend` field is unused.** The dataclass has a `backend: str = "skfolio"` field, but the service builds its own dict and uses the literal `"skfolio"` string directly. Either drop the field from `SkfolioResult` or wire it through. Currently it's dead.

7. **No schema-level constraint that `target_return` is meaningless when `mode != "efficient_return"`.** Pre-existing issue, but the new `backend` parameter makes the field-vs-mode-vs-backend matrix bigger. If the caller sends `{"backend": "skfolio", "mode": "hrp", "target_return": 0.20}`, the `target_return` is silently ignored. A `model_validator` would catch this earlier.

8. **No `__init__.py` export means IDEs can't auto-import.** Deliberate, but worth flagging for future readers — they'll wonder why `from core.portfolio_opt import skfolio_adapter` works while `from core.portfolio_opt import optimise as sk_optimise` doesn't. The submodule path is the only entry.

---

## Follow-Ups (out of scope for the shipped commit)

In rough priority order:

1. **Tests for the skfolio path.** At minimum, two `pytest.importorskip("skfolio")`-gated tests: one happy-path `mean_risk`, one `hrp`. Without these, future refactors can silently break the new branch.

2. **HRP-only request-body fields.** HRP doesn't use `risk_free_rate` and ignores `target_return`. A pydantic `model_validator` could:
   - Reject `target_return` unless `mode == "efficient_return"`.
   - Warn (or accept-and-ignore) `risk_free_rate` when `mode == "hrp"`.

3. **`riskfolio-lib` backend.** Same shape as the skfolio adapter (lazy import, `is_available()`, mirror `OptimizationResult`). If/when we add this, that's the moment to extract a `Protocol`:
   ```python
   class OptimizerBackend(Protocol):
       def is_available(self) -> bool: ...
       def optimise(self, prices: pd.DataFrame, *, mode: str, risk_free_rate: float) -> OptimizationResult: ...
   ```
   …and replace the two `if backend == "x":` branches with a registry lookup.

4. **Persist optimisation runs.** A new `optimization_runs` SQLite table keyed on `(broker_account_id, requested_at)` with the request JSON + the response JSON. Lets the UI render history and lets the user re-pin a previous suggestion.

5. **Custom-allocation backend (`vnpy`-style).** Walk-forward cross-validation comes for free with skfolio's `WalkForward` cv splitter, but it doesn't fit the current "one frame in, one weight vector out" shape. Add a `cv: bool` flag and a richer response that carries per-fold scores.

6. **Distinguish "skfolio missing" from "yfinance empty" at the HTTP layer.** Today both surface as 503; the former is permanent. Add `BackendUnavailableError` and map to 501 Not Implemented in the router.

7. **Frontend: backend toggle in the optimisation panel.** The wire field is already there; the UI can add a `<select>` with `pyportfolioopt` / `skfolio` once skfolio is part of the deployed image (or behind a feature flag for self-hosted users).

8. **Docstring + OpenAPI summary refresh.** Add `hrp` and `backend` to the `optimize_portfolio` docstring so the OpenAPI surface explains the new options.

9. **Logging.** Replace the bare `except Exception:` HRP-stats fallback with a `logger.warning("skfolio HRP stats lookup failed: %s", exc)` so silent zeros are detectable in production.
