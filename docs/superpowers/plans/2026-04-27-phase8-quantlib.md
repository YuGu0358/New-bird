# Phase 8 — QuantLib Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the open-source QuantLib library (already a Fincept-Terminal dependency) into a clean service layer + API. Expose four flagship quantitative tools: option pricing (Black-Scholes + binomial), option Greeks, bond yield/risk metrics (YTM, duration, convexity), and historical/parametric VaR. Frontend's QUANTLIB tab becomes a real product with form-driven calculators.

**Architecture (3-layer split, same shape as P7):**

```
backend/core/quantlib/   (pure wrappers around QuantLib C++)
    options.py           BS price + binomial price + Greeks
    bonds.py             ytm + duration + convexity
    risk.py              parametric/historical VaR
    base.py              shared types (OptionParams, BondParams, etc.)

backend/app/services/quantlib_service.py
    Validates inputs, dispatches to core/quantlib/, returns plain dicts.

backend/app/routers/quantlib.py
    5 POST endpoints accepting Pydantic request models.
```

**Tech Stack:** Python 3.13, QuantLib 1.42 (already installed), Pydantic v2, FastAPI.

**Out of scope (deferred):**
- Volatility surface fitting (needs market data; future P8.5).
- Yield curve bootstrap (needs term-structure data; future P8.5).
- Monte Carlo option pricing (heavier compute; optional add later).
- Frontend QuantLab page implementation — P8 only adds the backend; frontend wiring happens after P9 lands per user direction.

---

## File Structure

### New
| Path | Responsibility |
|---|---|
| `backend/core/quantlib/__init__.py` | Public API re-exports |
| `backend/core/quantlib/base.py` | Common dataclasses + helpers |
| `backend/core/quantlib/options.py` | `price_european_bs()`, `price_american_binomial()`, `greeks_european_bs()` |
| `backend/core/quantlib/bonds.py` | `bond_yield_to_maturity()`, `bond_risk_metrics()` |
| `backend/core/quantlib/risk.py` | `parametric_var()`, `historical_var()` |
| `backend/app/services/quantlib_service.py` | Thin wrapper, exception mapping, validation |
| `backend/app/models/quantlib.py` | API request/response Pydantic models |
| `backend/app/routers/quantlib.py` | 5 endpoints |

### New tests
| Path | Coverage |
|---|---|
| `backend/tests/test_quantlib_options.py` | BS price vs known closed-form values; American > European premium for puts; Greeks signs/relations |
| `backend/tests/test_quantlib_bonds.py` | Coupon bond YTM round-trip; duration positive; modified duration < Macaulay |
| `backend/tests/test_quantlib_risk.py` | Parametric VaR signs/scaling; historical VaR matches numpy quantile |
| `backend/tests/test_app_smoke.py` (append) | One smoke per endpoint via TestClient |

### Modified
| File | Change |
|---|---|
| `backend/requirements.txt` | Add `QuantLib` |
| `backend/app/models/__init__.py` | Re-export new models |
| `backend/app/main.py` | Register `quantlib_router` |
| `backend/tests/test_openapi_parity.py` | Add 5 routes |

### Untouched
- All P0–P7 code paths; this phase only adds.

---

## Pre-flight

- [ ] Confirm baseline:
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **152 passed**.

- [ ] Branch:
```bash
cd ~/NewBirdClaude
git checkout feat/p7-ai-council
git checkout -b feat/p8-quantlib
```

- [ ] Install QuantLib if not already:
```bash
pip install QuantLib
python -c "import QuantLib as ql; print(ql.__version__)"
```
Expected: prints `1.42.1` or newer.

---

## Task 1: Base types + package skeleton

**Files:**
- Create: `backend/core/quantlib/__init__.py`
- Create: `backend/core/quantlib/base.py`

- [ ] **Step 1: `base.py`**

```python
"""Shared types for QuantLib wrappers.

QuantLib uses its own date/calendar/option-type primitives. We translate
between simple Python types and QuantLib types here so the wrappers stay
clean and the API layer stays QuantLib-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal


OptionRight = Literal["call", "put"]
ExerciseStyle = Literal["european", "american"]


class QuantLibError(RuntimeError):
    """Wrapper around QuantLib::Error for consistent error mapping."""


@dataclass(frozen=True)
class OptionParams:
    """Inputs for European/American vanilla option pricing."""

    spot: float                # underlying price
    strike: float              # strike
    rate: float                # risk-free rate (annualized, decimal e.g. 0.05)
    dividend: float            # continuous dividend yield (decimal)
    volatility: float          # annualized volatility (decimal)
    expiry: date               # option expiry date
    valuation: date            # today / pricing date
    right: OptionRight = "call"

    def days_to_expiry(self) -> int:
        return (self.expiry - self.valuation).days


@dataclass(frozen=True)
class GreeksResult:
    delta: float
    gamma: float
    vega: float       # per 1.0 vol move (i.e. 100 vol points)
    theta: float      # per year
    rho: float        # per 1.0 rate move


@dataclass(frozen=True)
class BondParams:
    """Inputs for fixed-rate coupon bond analytics.

    `coupon_rate` is the annualized decimal coupon (e.g. 0.05 for 5%).
    `frequency` is coupons per year (1, 2, 4, 12).
    `face` is the redemption value at maturity.
    `clean_price` is the market price (per 100 face) used as reference.
    """

    settlement: date
    maturity: date
    coupon_rate: float
    frequency: int = 2
    face: float = 100.0
    clean_price: float = 100.0


@dataclass(frozen=True)
class BondAnalytics:
    yield_to_maturity: float        # annualized decimal
    macaulay_duration: float        # years
    modified_duration: float        # years
    convexity: float


@dataclass(frozen=True)
class VaRResult:
    """All values are POSITIVE numbers representing potential loss in USD."""

    var: float                       # Value at Risk
    cvar: float                      # Conditional VaR (Expected Shortfall)
    confidence: float                # e.g. 0.95
    horizon_days: int                # e.g. 1
    method: Literal["parametric", "historical"]
```

- [ ] **Step 2: `__init__.py` (filled in Task 5)**

```python
"""QuantLib wrappers — option pricing, bond analytics, risk metrics."""
from __future__ import annotations

from core.quantlib.base import (
    BondAnalytics,
    BondParams,
    ExerciseStyle,
    GreeksResult,
    OptionParams,
    OptionRight,
    QuantLibError,
    VaRResult,
)

__all__ = [
    "BondAnalytics",
    "BondParams",
    "ExerciseStyle",
    "GreeksResult",
    "OptionParams",
    "OptionRight",
    "QuantLibError",
    "VaRResult",
]
```

- [ ] **Step 3: Smoke + tests**

```bash
python -c "from core.quantlib import OptionParams, BondParams, VaRResult; print('ok')"
pytest tests/ -q
```
Expected: `ok`; **152 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/quantlib/__init__.py backend/core/quantlib/base.py
git commit -m "feat(quantlib): add base types (OptionParams, BondParams, VaRResult)"
```

---

## Task 2: Options pricing + Greeks (TDD)

**Files:**
- Create: `backend/core/quantlib/options.py`
- Create: `backend/tests/test_quantlib_options.py`

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_quantlib_options.py
"""Black-Scholes + binomial option pricing + Greeks."""
from __future__ import annotations

from datetime import date

import pytest

from core.quantlib import OptionParams
from core.quantlib.options import (
    greeks_european_bs,
    price_american_binomial,
    price_european_bs,
)


def _atm_call(*, vol: float = 0.20, days: int = 365, rate: float = 0.05) -> OptionParams:
    today = date(2025, 1, 1)
    return OptionParams(
        spot=100.0,
        strike=100.0,
        rate=rate,
        dividend=0.0,
        volatility=vol,
        valuation=today,
        expiry=date(today.year + 1, today.month, today.day) if days >= 365 else today.replace(day=today.day),
        right="call",
    )


def test_european_bs_atm_call_known_value() -> None:
    """At-the-money 1-year call, vol 20%, rate 5%, no dividend.
    Closed form ≈ 10.4506."""
    today = date(2025, 1, 1)
    params = OptionParams(
        spot=100.0, strike=100.0, rate=0.05, dividend=0.0,
        volatility=0.20, valuation=today, expiry=date(2026, 1, 1), right="call",
    )
    price = price_european_bs(params)
    assert price == pytest.approx(10.4506, abs=0.01)


def test_european_bs_atm_put_known_value() -> None:
    """ATM 1-year put, vol 20%, rate 5%, no dividend.
    Closed form ≈ 5.5735 (put-call parity from above)."""
    today = date(2025, 1, 1)
    params = OptionParams(
        spot=100.0, strike=100.0, rate=0.05, dividend=0.0,
        volatility=0.20, valuation=today, expiry=date(2026, 1, 1), right="put",
    )
    price = price_european_bs(params)
    assert price == pytest.approx(5.5735, abs=0.01)


def test_american_put_premium_over_european() -> None:
    """American put should be worth at least as much as European put
    (early exercise has option value when dividend yield is low)."""
    today = date(2025, 1, 1)
    params = OptionParams(
        spot=100.0, strike=110.0, rate=0.05, dividend=0.0,
        volatility=0.20, valuation=today, expiry=date(2026, 1, 1), right="put",
    )
    eu = price_european_bs(params)
    am = price_american_binomial(params, steps=200)
    assert am >= eu - 1e-6  # binomial should match or exceed BS for puts


def test_greeks_atm_call_signs() -> None:
    today = date(2025, 1, 1)
    params = OptionParams(
        spot=100.0, strike=100.0, rate=0.05, dividend=0.0,
        volatility=0.20, valuation=today, expiry=date(2026, 1, 1), right="call",
    )
    g = greeks_european_bs(params)
    assert 0.4 < g.delta < 0.7         # ATM call delta near 0.5-0.65
    assert g.gamma > 0
    assert g.vega > 0
    assert g.theta < 0                  # call decays
    assert g.rho > 0                    # call benefits from rate rise


def test_greeks_atm_put_signs() -> None:
    today = date(2025, 1, 1)
    params = OptionParams(
        spot=100.0, strike=100.0, rate=0.05, dividend=0.0,
        volatility=0.20, valuation=today, expiry=date(2026, 1, 1), right="put",
    )
    g = greeks_european_bs(params)
    assert -0.7 < g.delta < -0.3
    assert g.gamma > 0
    assert g.vega > 0
    assert g.rho < 0                    # put hurt by rate rise
```

- [ ] **Step 2: Implement `options.py`**

```python
# backend/core/quantlib/options.py
"""Black-Scholes + binomial option pricing using QuantLib.

Stays focused: vanilla European/American calls and puts. Anything path-
dependent (Asian, barrier, lookback) is out of scope.
"""
from __future__ import annotations

from datetime import date

import QuantLib as ql

from core.quantlib.base import (
    GreeksResult,
    OptionParams,
    QuantLibError,
)


# ---------------------------------------------------------------------------
# QuantLib helpers — keep all the Python↔QL translation in one place
# ---------------------------------------------------------------------------


def _to_ql_date(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _option_type(right: str) -> int:
    if right == "call":
        return ql.Option.Call
    if right == "put":
        return ql.Option.Put
    raise QuantLibError(f"Unsupported option right: {right!r}")


def _build_market(params: OptionParams):
    """Construct the BS market: spot, rate term-structure, dividend term-
    structure, vol surface — anchored on the valuation date."""
    valuation = _to_ql_date(params.valuation)
    ql.Settings.instance().evaluationDate = valuation

    day_count = ql.Actual365Fixed()
    calendar = ql.NullCalendar()

    spot_handle = ql.QuoteHandle(ql.SimpleQuote(params.spot))
    rate_handle = ql.YieldTermStructureHandle(
        ql.FlatForward(valuation, params.rate, day_count)
    )
    dividend_handle = ql.YieldTermStructureHandle(
        ql.FlatForward(valuation, params.dividend, day_count)
    )
    vol_handle = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(valuation, calendar, params.volatility, day_count)
    )

    process = ql.BlackScholesMertonProcess(
        spot_handle, dividend_handle, rate_handle, vol_handle,
    )
    return process, day_count


def _european_option(params: OptionParams) -> ql.VanillaOption:
    payoff = ql.PlainVanillaPayoff(_option_type(params.right), params.strike)
    exercise = ql.EuropeanExercise(_to_ql_date(params.expiry))
    return ql.VanillaOption(payoff, exercise)


def _american_option(params: OptionParams) -> ql.VanillaOption:
    payoff = ql.PlainVanillaPayoff(_option_type(params.right), params.strike)
    exercise = ql.AmericanExercise(
        _to_ql_date(params.valuation),
        _to_ql_date(params.expiry),
    )
    return ql.VanillaOption(payoff, exercise)


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def price_european_bs(params: OptionParams) -> float:
    """Closed-form Black-Scholes price for a European call/put."""
    if params.expiry <= params.valuation:
        raise QuantLibError("expiry must be after valuation date")
    if params.spot <= 0 or params.strike <= 0:
        raise QuantLibError("spot and strike must be > 0")

    process, _ = _build_market(params)
    option = _european_option(params)
    option.setPricingEngine(ql.AnalyticEuropeanEngine(process))
    return float(option.NPV())


def price_american_binomial(params: OptionParams, *, steps: int = 200) -> float:
    """Cox-Ross-Rubinstein binomial tree price for an American call/put."""
    if params.expiry <= params.valuation:
        raise QuantLibError("expiry must be after valuation date")
    if steps < 10:
        raise QuantLibError("steps must be >= 10")

    process, _ = _build_market(params)
    option = _american_option(params)
    option.setPricingEngine(ql.BinomialVanillaEngine(process, "crr", steps))
    return float(option.NPV())


def greeks_european_bs(params: OptionParams) -> GreeksResult:
    """Greeks computed analytically by QuantLib for a European option."""
    process, _ = _build_market(params)
    option = _european_option(params)
    option.setPricingEngine(ql.AnalyticEuropeanEngine(process))
    # Force NPV calc so Greeks are populated.
    option.NPV()
    return GreeksResult(
        delta=float(option.delta()),
        gamma=float(option.gamma()),
        vega=float(option.vega()),
        theta=float(option.theta()),
        rho=float(option.rho()),
    )
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_quantlib_options.py -v
pytest tests/ -q
```
Expected: 5 PASS in options test file; **157 passed** total.

- [ ] **Step 4: Commit**

```bash
git add backend/core/quantlib/options.py backend/tests/test_quantlib_options.py
git commit -m "feat(quantlib): Black-Scholes + binomial option pricing + analytic Greeks"
```

---

## Task 3: Bond analytics (TDD)

**Files:**
- Create: `backend/core/quantlib/bonds.py`
- Create: `backend/tests/test_quantlib_bonds.py`

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_quantlib_bonds.py
"""Bond yield-to-maturity, duration, convexity."""
from __future__ import annotations

from datetime import date

import pytest

from core.quantlib import BondParams
from core.quantlib.bonds import bond_risk_metrics, bond_yield_to_maturity


def _five_year_par_bond(coupon: float = 0.05, price: float = 100.0) -> BondParams:
    return BondParams(
        settlement=date(2025, 1, 1),
        maturity=date(2030, 1, 1),
        coupon_rate=coupon,
        frequency=2,
        face=100.0,
        clean_price=price,
    )


def test_par_bond_ytm_equals_coupon() -> None:
    """A bond trading at par with semi-annual coupons should have YTM ≈ coupon rate."""
    params = _five_year_par_bond(coupon=0.05, price=100.0)
    ytm = bond_yield_to_maturity(params)
    assert ytm == pytest.approx(0.05, abs=0.001)


def test_premium_bond_ytm_below_coupon() -> None:
    """Bond priced above par → YTM < coupon."""
    params = _five_year_par_bond(coupon=0.05, price=105.0)
    ytm = bond_yield_to_maturity(params)
    assert ytm < 0.05


def test_discount_bond_ytm_above_coupon() -> None:
    """Bond priced below par → YTM > coupon."""
    params = _five_year_par_bond(coupon=0.05, price=95.0)
    ytm = bond_yield_to_maturity(params)
    assert ytm > 0.05


def test_par_bond_metrics_make_sense() -> None:
    metrics = bond_risk_metrics(_five_year_par_bond())
    # 5-year par bond with 5% coupon: Macaulay duration ≈ 4.4-4.5 years
    assert 4.0 < metrics.macaulay_duration < 4.6
    # Modified duration < Macaulay (Mod = Mac / (1 + y/m))
    assert metrics.modified_duration < metrics.macaulay_duration
    # Convexity is positive
    assert metrics.convexity > 0


def test_zero_coupon_duration_equals_maturity() -> None:
    """A zero-coupon bond's Macaulay duration equals its maturity in years."""
    params = BondParams(
        settlement=date(2025, 1, 1),
        maturity=date(2030, 1, 1),
        coupon_rate=0.0,
        frequency=2,
        face=100.0,
        clean_price=80.0,
    )
    metrics = bond_risk_metrics(params)
    # 5-year zero, Macaulay ≈ 5.0
    assert metrics.macaulay_duration == pytest.approx(5.0, abs=0.05)
```

- [ ] **Step 2: Implement `bonds.py`**

```python
# backend/core/quantlib/bonds.py
"""Fixed-rate coupon bond analytics: YTM, duration, convexity."""
from __future__ import annotations

from datetime import date

import QuantLib as ql

from core.quantlib.base import BondAnalytics, BondParams, QuantLibError


_FREQUENCY_MAP = {
    1: ql.Annual,
    2: ql.Semiannual,
    4: ql.Quarterly,
    12: ql.Monthly,
}


def _to_ql_date(d: date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _build_bond(params: BondParams) -> ql.FixedRateBond:
    if params.frequency not in _FREQUENCY_MAP:
        raise QuantLibError(
            f"Unsupported coupon frequency: {params.frequency}. "
            f"Choose from {sorted(_FREQUENCY_MAP)}."
        )
    if params.maturity <= params.settlement:
        raise QuantLibError("maturity must be after settlement")

    settlement = _to_ql_date(params.settlement)
    maturity = _to_ql_date(params.maturity)
    ql.Settings.instance().evaluationDate = settlement

    schedule = ql.MakeSchedule(
        effectiveDate=settlement,
        terminationDate=maturity,
        frequency=_FREQUENCY_MAP[params.frequency],
        calendar=ql.NullCalendar(),
        convention=ql.Unadjusted,
        terminationDateConvention=ql.Unadjusted,
        rule=ql.DateGeneration.Backward,
        endOfMonth=False,
    )
    day_count = ql.ActualActual(ql.ActualActual.ISDA)
    return ql.FixedRateBond(
        0,                              # settlement_days
        params.face,
        schedule,
        [params.coupon_rate],
        day_count,
        ql.Unadjusted,
        params.face,                    # redemption == face
    )


def bond_yield_to_maturity(params: BondParams) -> float:
    """Solve for the constant yield that prices the bond at clean_price."""
    bond = _build_bond(params)
    day_count = ql.ActualActual(ql.ActualActual.ISDA)
    return float(bond.bondYield(
        params.clean_price,
        day_count,
        ql.Compounded,
        _FREQUENCY_MAP[params.frequency],
    ))


def bond_risk_metrics(params: BondParams) -> BondAnalytics:
    """Yield-to-maturity + Macaulay/modified duration + convexity."""
    bond = _build_bond(params)
    day_count = ql.ActualActual(ql.ActualActual.ISDA)
    ytm = bond.bondYield(
        params.clean_price,
        day_count,
        ql.Compounded,
        _FREQUENCY_MAP[params.frequency],
    )
    interest_rate = ql.InterestRate(
        ytm,
        day_count,
        ql.Compounded,
        _FREQUENCY_MAP[params.frequency],
    )
    macaulay = ql.BondFunctions.duration(
        bond, interest_rate, ql.Duration.Macaulay,
    )
    modified = ql.BondFunctions.duration(
        bond, interest_rate, ql.Duration.Modified,
    )
    convex = ql.BondFunctions.convexity(bond, interest_rate)

    return BondAnalytics(
        yield_to_maturity=float(ytm),
        macaulay_duration=float(macaulay),
        modified_duration=float(modified),
        convexity=float(convex),
    )
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_quantlib_bonds.py -v
pytest tests/ -q
```
Expected: 5 PASS; **162 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/quantlib/bonds.py backend/tests/test_quantlib_bonds.py
git commit -m "feat(quantlib): bond YTM + Macaulay/modified duration + convexity"
```

---

## Task 4: VaR / CVaR (TDD)

**Files:**
- Create: `backend/core/quantlib/risk.py`
- Create: `backend/tests/test_quantlib_risk.py`

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_quantlib_risk.py
"""Parametric + historical VaR / CVaR."""
from __future__ import annotations

import math

import pytest

from core.quantlib.risk import historical_var, parametric_var


def test_parametric_var_one_day_normal() -> None:
    """For mean=0, sigma=0.01, 1-day horizon, 95% conf:
    VaR = 1.645 * 0.01 * sqrt(1) ≈ 0.01645 per unit notional.
    Notional 1,000,000 → VaR ≈ 16,449."""
    result = parametric_var(
        notional=1_000_000.0,
        mean_return=0.0,
        std_return=0.01,
        confidence=0.95,
        horizon_days=1,
    )
    assert result.var == pytest.approx(16449, rel=0.05)
    assert result.cvar > result.var          # CVaR is conservative


def test_parametric_var_scales_with_horizon() -> None:
    """VaR should scale with sqrt(horizon)."""
    one_day = parametric_var(
        notional=1_000_000.0, mean_return=0.0, std_return=0.01,
        confidence=0.95, horizon_days=1,
    )
    ten_day = parametric_var(
        notional=1_000_000.0, mean_return=0.0, std_return=0.01,
        confidence=0.95, horizon_days=10,
    )
    ratio = ten_day.var / one_day.var
    assert ratio == pytest.approx(math.sqrt(10), rel=0.02)


def test_historical_var_matches_quantile() -> None:
    """For uniformly distributed returns we know the quantile exactly."""
    # 100 returns from -0.10 to +0.09 step 0.001 (negative-biased)
    returns = [(-0.10 + i * 0.002) for i in range(100)]
    result = historical_var(
        notional=1_000_000.0,
        returns=returns,
        confidence=0.95,
        horizon_days=1,
    )
    # 5th percentile of returns ≈ -0.090
    # VaR (positive loss) ≈ 0.090 * 1,000,000 = 90,000
    assert result.var == pytest.approx(90_000, rel=0.05)


def test_historical_var_rejects_too_few_returns() -> None:
    with pytest.raises(ValueError):
        historical_var(notional=1.0, returns=[0.01], confidence=0.95, horizon_days=1)


def test_parametric_var_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        parametric_var(notional=1.0, mean_return=0, std_return=0.01, confidence=1.5, horizon_days=1)
```

- [ ] **Step 2: Implement `risk.py`**

```python
# backend/core/quantlib/risk.py
"""Value-at-Risk and Conditional VaR.

Uses pure-Python statistics (no QuantLib dependency for VaR — it's
straightforward stats) to keep the wrappers focused. QuantLib is used
only when its primitives genuinely help (option pricing, bond analytics).
"""
from __future__ import annotations

import math
import statistics
from typing import Sequence

from core.quantlib.base import VaRResult


# Cached z-scores for common confidence levels (2-sided lower tail).
_Z_TABLE = {
    0.90: 1.2816,
    0.95: 1.6449,
    0.975: 1.96,
    0.99: 2.3263,
    0.995: 2.5758,
    0.999: 3.0902,
}


def _z_score(confidence: float) -> float:
    """Inverse normal CDF for `confidence` (lower-tail). Uses a table for
    common levels; falls back to numerical approximation otherwise.

    The Beasley-Springer-Moro approximation is plenty accurate for VaR.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")

    if confidence in _Z_TABLE:
        return _Z_TABLE[confidence]

    # Beasley-Springer-Moro inverse normal CDF.
    a = (-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00)

    p = confidence
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def parametric_var(
    *,
    notional: float,
    mean_return: float,
    std_return: float,
    confidence: float,
    horizon_days: int,
) -> VaRResult:
    """Variance-covariance VaR assuming normally distributed returns.

    Inputs are per-period (typically daily) return statistics. We scale to
    `horizon_days` via sqrt(time).
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    if notional <= 0:
        raise ValueError("notional must be > 0")
    if std_return < 0:
        raise ValueError("std_return must be >= 0")

    z = _z_score(confidence)
    horizon_std = std_return * math.sqrt(horizon_days)
    horizon_mean = mean_return * horizon_days

    # VaR is a POSITIVE loss number.
    var = max(0.0, (z * horizon_std - horizon_mean) * notional)

    # Closed-form Normal CVaR: phi(z) / (1 - F(z)) * sigma - mean
    pdf_z = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    cvar = max(0.0, ((pdf_z / (1 - confidence)) * horizon_std - horizon_mean) * notional)

    return VaRResult(
        var=float(var),
        cvar=float(cvar),
        confidence=float(confidence),
        horizon_days=int(horizon_days),
        method="parametric",
    )


def historical_var(
    *,
    notional: float,
    returns: Sequence[float],
    confidence: float,
    horizon_days: int,
) -> VaRResult:
    """Empirical-quantile VaR over a return series.

    `returns` are PER-PERIOD (typically daily). We aggregate to the horizon
    via sqrt-of-time scaling on the empirical loss quantile.
    """
    if len(returns) < 30:
        raise ValueError("Need at least 30 returns for historical VaR")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    if notional <= 0:
        raise ValueError("notional must be > 0")

    sorted_returns = sorted(returns)
    n = len(sorted_returns)
    rank = max(0, min(n - 1, int(math.floor((1 - confidence) * n))))
    quantile_return = sorted_returns[rank]
    # Loss is the magnitude of the negative quantile.
    daily_loss = max(0.0, -quantile_return)
    horizon_loss = daily_loss * math.sqrt(horizon_days)

    # CVaR = mean of returns at or below quantile, taken positive.
    tail = sorted_returns[: rank + 1]
    if tail:
        avg_tail = statistics.fmean(tail)
        daily_cvar = max(0.0, -avg_tail)
    else:
        daily_cvar = daily_loss
    horizon_cvar = daily_cvar * math.sqrt(horizon_days)

    return VaRResult(
        var=float(horizon_loss * notional),
        cvar=float(horizon_cvar * notional),
        confidence=float(confidence),
        horizon_days=int(horizon_days),
        method="historical",
    )
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_quantlib_risk.py -v
pytest tests/ -q
```
Expected: 5 PASS; **167 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/quantlib/risk.py backend/tests/test_quantlib_risk.py
git commit -m "feat(quantlib): parametric + historical VaR / CVaR"
```

---

## Task 5: Final `core/quantlib/__init__.py` re-exports + service

**Files:**
- Modify: `backend/core/quantlib/__init__.py`
- Create: `backend/app/services/quantlib_service.py`

- [ ] **Step 1: Replace `__init__.py`**

```python
"""QuantLib wrappers — option pricing, bond analytics, risk metrics."""
from __future__ import annotations

from core.quantlib.base import (
    BondAnalytics,
    BondParams,
    ExerciseStyle,
    GreeksResult,
    OptionParams,
    OptionRight,
    QuantLibError,
    VaRResult,
)
from core.quantlib.bonds import bond_risk_metrics, bond_yield_to_maturity
from core.quantlib.options import (
    greeks_european_bs,
    price_american_binomial,
    price_european_bs,
)
from core.quantlib.risk import historical_var, parametric_var

__all__ = [
    "BondAnalytics",
    "BondParams",
    "ExerciseStyle",
    "GreeksResult",
    "OptionParams",
    "OptionRight",
    "QuantLibError",
    "VaRResult",
    "bond_risk_metrics",
    "bond_yield_to_maturity",
    "greeks_european_bs",
    "historical_var",
    "parametric_var",
    "price_american_binomial",
    "price_european_bs",
]
```

- [ ] **Step 2: Service**

```python
# backend/app/services/quantlib_service.py
"""Thin service wrapper — adapts API request models to core/quantlib calls.

Catches QuantLibError + ValueError and re-raises as a single ServiceError
type the router can map to HTTP 422.
"""
from __future__ import annotations

from datetime import date as DateType
from typing import Any

from core.quantlib import (
    BondParams,
    OptionParams,
    QuantLibError,
    bond_risk_metrics,
    bond_yield_to_maturity,
    greeks_european_bs,
    historical_var,
    parametric_var,
    price_american_binomial,
    price_european_bs,
)


class QuantLibInputError(ValueError):
    """User-supplied inputs failed validation. Maps to HTTP 422."""


def _coerce_option_params(payload: dict[str, Any]) -> OptionParams:
    try:
        return OptionParams(
            spot=float(payload["spot"]),
            strike=float(payload["strike"]),
            rate=float(payload["rate"]),
            dividend=float(payload.get("dividend", 0.0)),
            volatility=float(payload["volatility"]),
            valuation=_to_date(payload["valuation"]),
            expiry=_to_date(payload["expiry"]),
            right=str(payload.get("right", "call")).lower(),  # type: ignore[arg-type]
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise QuantLibInputError(str(exc)) from exc


def _coerce_bond_params(payload: dict[str, Any]) -> BondParams:
    try:
        return BondParams(
            settlement=_to_date(payload["settlement"]),
            maturity=_to_date(payload["maturity"]),
            coupon_rate=float(payload["coupon_rate"]),
            frequency=int(payload.get("frequency", 2)),
            face=float(payload.get("face", 100.0)),
            clean_price=float(payload.get("clean_price", 100.0)),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise QuantLibInputError(str(exc)) from exc


def _to_date(value: Any) -> DateType:
    if isinstance(value, DateType):
        return value
    if isinstance(value, str):
        return DateType.fromisoformat(value)
    raise QuantLibInputError(f"Cannot parse date: {value!r}")


# ---------------------------------------------------------------------------
# Public service surface
# ---------------------------------------------------------------------------


def option_price(payload: dict[str, Any]) -> dict[str, Any]:
    params = _coerce_option_params(payload)
    style = str(payload.get("style", "european")).lower()
    try:
        if style == "european":
            price = price_european_bs(params)
        elif style == "american":
            steps = int(payload.get("steps", 200))
            price = price_american_binomial(params, steps=steps)
        else:
            raise QuantLibInputError(f"Unknown exercise style: {style!r}")
    except QuantLibError as exc:
        raise QuantLibInputError(str(exc)) from exc
    return {
        "style": style,
        "right": params.right,
        "price": price,
        "days_to_expiry": params.days_to_expiry(),
    }


def option_greeks(payload: dict[str, Any]) -> dict[str, Any]:
    params = _coerce_option_params(payload)
    try:
        g = greeks_european_bs(params)
    except QuantLibError as exc:
        raise QuantLibInputError(str(exc)) from exc
    return {
        "delta": g.delta,
        "gamma": g.gamma,
        "vega": g.vega,
        "theta": g.theta,
        "rho": g.rho,
    }


def bond_yield(payload: dict[str, Any]) -> dict[str, Any]:
    params = _coerce_bond_params(payload)
    try:
        ytm = bond_yield_to_maturity(params)
    except QuantLibError as exc:
        raise QuantLibInputError(str(exc)) from exc
    return {"yield_to_maturity": ytm}


def bond_risk(payload: dict[str, Any]) -> dict[str, Any]:
    params = _coerce_bond_params(payload)
    try:
        metrics = bond_risk_metrics(params)
    except QuantLibError as exc:
        raise QuantLibInputError(str(exc)) from exc
    return {
        "yield_to_maturity": metrics.yield_to_maturity,
        "macaulay_duration": metrics.macaulay_duration,
        "modified_duration": metrics.modified_duration,
        "convexity": metrics.convexity,
    }


def value_at_risk(payload: dict[str, Any]) -> dict[str, Any]:
    method = str(payload.get("method", "parametric")).lower()
    notional = float(payload.get("notional", 0.0))
    confidence = float(payload.get("confidence", 0.95))
    horizon_days = int(payload.get("horizon_days", 1))

    if method == "parametric":
        result = parametric_var(
            notional=notional,
            mean_return=float(payload.get("mean_return", 0.0)),
            std_return=float(payload.get("std_return", 0.0)),
            confidence=confidence,
            horizon_days=horizon_days,
        )
    elif method == "historical":
        result = historical_var(
            notional=notional,
            returns=list(payload.get("returns") or []),
            confidence=confidence,
            horizon_days=horizon_days,
        )
    else:
        raise QuantLibInputError(f"Unknown VaR method: {method!r}")

    return {
        "var": result.var,
        "cvar": result.cvar,
        "confidence": result.confidence,
        "horizon_days": result.horizon_days,
        "method": result.method,
    }
```

- [ ] **Step 3: Smoke + tests**

```bash
python -c "
from app.services import quantlib_service
print(quantlib_service.option_price({
    'spot': 100, 'strike': 100, 'rate': 0.05,
    'volatility': 0.20, 'valuation': '2025-01-01', 'expiry': '2026-01-01', 'right': 'call'
}))
"
pytest tests/ -q
```
Expected: prints option price ~10.45; **167 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/quantlib/__init__.py backend/app/services/quantlib_service.py
git commit -m "feat(quantlib): expose framework public API + add quantlib_service"
```

---

## Task 6: API models + router

**Files:**
- Create: `backend/app/models/quantlib.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/routers/quantlib.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_app_smoke.py`
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: API models**

```python
# backend/app/models/quantlib.py
"""QuantLib API request/response models."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OptionPriceRequest(BaseModel):
    spot: float = Field(..., gt=0)
    strike: float = Field(..., gt=0)
    rate: float = Field(..., ge=-0.5, le=1.0)
    dividend: float = Field(0.0, ge=-0.5, le=1.0)
    volatility: float = Field(..., gt=0, le=5.0)
    valuation: date
    expiry: date
    right: Literal["call", "put"] = "call"
    style: Literal["european", "american"] = "european"
    steps: int = Field(200, ge=20, le=2000)


class OptionPriceResponse(BaseModel):
    style: str
    right: str
    price: float
    days_to_expiry: int


class OptionGreeksRequest(BaseModel):
    spot: float = Field(..., gt=0)
    strike: float = Field(..., gt=0)
    rate: float = Field(..., ge=-0.5, le=1.0)
    dividend: float = Field(0.0, ge=-0.5, le=1.0)
    volatility: float = Field(..., gt=0, le=5.0)
    valuation: date
    expiry: date
    right: Literal["call", "put"] = "call"


class OptionGreeksResponse(BaseModel):
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


class BondAnalyticsRequest(BaseModel):
    settlement: date
    maturity: date
    coupon_rate: float = Field(..., ge=0, le=1.0)
    frequency: Literal[1, 2, 4, 12] = 2
    face: float = Field(100.0, gt=0)
    clean_price: float = Field(100.0, gt=0)


class BondYieldResponse(BaseModel):
    yield_to_maturity: float


class BondRiskResponse(BaseModel):
    yield_to_maturity: float
    macaulay_duration: float
    modified_duration: float
    convexity: float


class VaRRequest(BaseModel):
    method: Literal["parametric", "historical"] = "parametric"
    notional: float = Field(..., gt=0)
    confidence: float = Field(0.95, gt=0, lt=1)
    horizon_days: int = Field(1, ge=1, le=365)
    # parametric inputs
    mean_return: float = 0.0
    std_return: float = 0.0
    # historical inputs
    returns: Optional[list[float]] = None


class VaRResponse(BaseModel):
    var: float
    cvar: float
    confidence: float
    horizon_days: int
    method: str
```

Update `app/models/__init__.py`: add the 9 new models to imports + `__all__` alphabetically.

- [ ] **Step 2: Router**

```python
# backend/app/routers/quantlib.py
"""QuantLib endpoints — option pricing, Greeks, bond analytics, VaR."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models import (
    BondAnalyticsRequest,
    BondRiskResponse,
    BondYieldResponse,
    OptionGreeksRequest,
    OptionGreeksResponse,
    OptionPriceRequest,
    OptionPriceResponse,
    VaRRequest,
    VaRResponse,
)
from app.services import quantlib_service
from app.services.quantlib_service import QuantLibInputError

router = APIRouter(prefix="/api/quantlib", tags=["quantlib"])


@router.post("/option/price", response_model=OptionPriceResponse)
async def option_price(request: OptionPriceRequest) -> OptionPriceResponse:
    try:
        return OptionPriceResponse(**quantlib_service.option_price(request.model_dump(mode="json")))
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@router.post("/option/greeks", response_model=OptionGreeksResponse)
async def option_greeks(request: OptionGreeksRequest) -> OptionGreeksResponse:
    try:
        return OptionGreeksResponse(**quantlib_service.option_greeks(request.model_dump(mode="json")))
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@router.post("/bond/yield", response_model=BondYieldResponse)
async def bond_yield(request: BondAnalyticsRequest) -> BondYieldResponse:
    try:
        return BondYieldResponse(**quantlib_service.bond_yield(request.model_dump(mode="json")))
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@router.post("/bond/risk", response_model=BondRiskResponse)
async def bond_risk(request: BondAnalyticsRequest) -> BondRiskResponse:
    try:
        return BondRiskResponse(**quantlib_service.bond_risk(request.model_dump(mode="json")))
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc


@router.post("/var", response_model=VaRResponse)
async def value_at_risk(request: VaRRequest) -> VaRResponse:
    try:
        return VaRResponse(**quantlib_service.value_at_risk(request.model_dump(mode="json")))
    except QuantLibInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
```

- [ ] **Step 3: Register in `main.py`**

Add `from app.routers import quantlib as quantlib_router` near the other router imports, then `app.include_router(quantlib_router.router)` in the registration block (alphabetical position is fine).

- [ ] **Step 4: Smoke tests**

Append to `tests/test_app_smoke.py`:

```python


def test_quantlib_option_price_endpoint(client) -> None:
    response = client.post("/api/quantlib/option/price", json={
        "spot": 100, "strike": 100, "rate": 0.05, "volatility": 0.20,
        "valuation": "2025-01-01", "expiry": "2026-01-01",
        "right": "call", "style": "european",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["price"] > 0
    assert body["right"] == "call"


def test_quantlib_var_endpoint(client) -> None:
    response = client.post("/api/quantlib/var", json={
        "method": "parametric",
        "notional": 1_000_000,
        "mean_return": 0,
        "std_return": 0.01,
        "confidence": 0.95,
        "horizon_days": 1,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["var"] > 0
    assert body["cvar"] >= body["var"]
```

- [ ] **Step 5: Update parity test**

Add to `tests/test_openapi_parity.py::EXPECTED_ROUTES`:
```python
("POST",   "/api/quantlib/bond/risk"),
("POST",   "/api/quantlib/bond/yield"),
("POST",   "/api/quantlib/option/greeks"),
("POST",   "/api/quantlib/option/price"),
("POST",   "/api/quantlib/var"),
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/ -q
```
Expected: **169 passed** (167 + 2 smoke).

- [ ] **Step 7: Add `QuantLib` to `requirements.txt`**

Append `QuantLib` to `backend/requirements.txt` so deployments pick it up.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/quantlib.py backend/app/models/__init__.py backend/app/routers/quantlib.py backend/app/main.py backend/tests/test_app_smoke.py backend/tests/test_openapi_parity.py backend/requirements.txt
git commit -m "feat(api): QuantLib endpoints (option price/greeks, bond yield/risk, VaR)"
```

---

## Task 7: Final verification + push

- [ ] **Step 1: Full sweep**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -v
```
Expected: **169 passed**.

- [ ] **Step 2: Live boot**

```bash
(uvicorn app.main:app --port 8765 > /tmp/uv.log 2>&1 &); sleep 3
echo "--- option price ---"
curl -s -X POST http://127.0.0.1:8765/api/quantlib/option/price \
  -H "Content-Type: application/json" \
  -d '{"spot":100,"strike":100,"rate":0.05,"volatility":0.20,"valuation":"2025-01-01","expiry":"2026-01-01","right":"call","style":"european"}'; echo

echo "--- greeks ---"
curl -s -X POST http://127.0.0.1:8765/api/quantlib/option/greeks \
  -H "Content-Type: application/json" \
  -d '{"spot":100,"strike":100,"rate":0.05,"volatility":0.20,"valuation":"2025-01-01","expiry":"2026-01-01","right":"call"}'; echo

echo "--- VaR ---"
curl -s -X POST http://127.0.0.1:8765/api/quantlib/var \
  -H "Content-Type: application/json" \
  -d '{"method":"parametric","notional":1000000,"mean_return":0,"std_return":0.01,"confidence":0.95,"horizon_days":1}'; echo

pkill -f "uvicorn app.main:app --port 8765"; sleep 1
grep -E "ERROR|Exception" /tmp/uv.log | head -3
```
Expected:
- option price returns ≈ `{"price": 10.45, ...}`
- greeks returns delta ~0.6, gamma > 0, vega > 0
- VaR returns `var ≈ 16449, cvar ≈ 20627`
- No errors in log.

- [ ] **Step 3: Push**

```bash
git push -u origin feat/p8-quantlib
```

---

## Done-criteria

- All tasks committed on `feat/p8-quantlib`, branched from `feat/p7-ai-council`.
- `pytest tests/` green: **169 passed**.
- New `core/quantlib/` package with options / bonds / risk modules.
- 5 new API routes locked in parity test.
- Strategy B and AI Council unaffected (no changes to those code paths).

After Phase 8 lands, **Phase 9 — Code editor + sandboxed strategy upload** completes the backend roadmap; then the frontend QuantLib + Code tabs can be wired in one final frontend phase.
