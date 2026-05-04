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
    """Par bond with semi-annual coupons → YTM ≈ coupon rate."""
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
    # 5-year par bond, 5% coupon: Macaulay duration ≈ 4.4-4.5 years
    assert 4.0 < metrics.macaulay_duration < 4.6
    assert metrics.modified_duration < metrics.macaulay_duration
    assert metrics.convexity > 0


def test_zero_coupon_duration_equals_maturity() -> None:
    """Zero-coupon bond's Macaulay duration ≈ maturity in years."""
    params = BondParams(
        settlement=date(2025, 1, 1),
        maturity=date(2030, 1, 1),
        coupon_rate=0.0,
        frequency=2,
        face=100.0,
        clean_price=80.0,
    )
    metrics = bond_risk_metrics(params)
    assert metrics.macaulay_duration == pytest.approx(5.0, abs=0.05)
