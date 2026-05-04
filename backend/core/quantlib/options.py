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
