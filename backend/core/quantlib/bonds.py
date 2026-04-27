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
        terminalDateConvention=ql.Unadjusted,
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
        ql.BondPrice(params.clean_price, ql.BondPrice.Clean),
        day_count,
        ql.Compounded,
        _FREQUENCY_MAP[params.frequency],
    ))


def bond_risk_metrics(params: BondParams) -> BondAnalytics:
    """Yield-to-maturity + Macaulay/modified duration + convexity."""
    bond = _build_bond(params)
    day_count = ql.ActualActual(ql.ActualActual.ISDA)
    ytm = bond.bondYield(
        ql.BondPrice(params.clean_price, ql.BondPrice.Clean),
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
