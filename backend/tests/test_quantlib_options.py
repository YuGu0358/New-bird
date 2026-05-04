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


def test_european_bs_atm_call_known_value() -> None:
    """At-the-money 1-year call, vol 20%, rate 5%, no dividend.
    Closed form ≈ 10.4506."""
    today = date(2025, 1, 1)
    params = OptionParams(
        spot=100.0, strike=100.0, rate=0.05, dividend=0.0,
        volatility=0.20, valuation=today, expiry=date(2026, 1, 1), right="call",
    )
    price = price_european_bs(params)
    assert price == pytest.approx(10.4506, abs=0.05)


def test_european_bs_atm_put_known_value() -> None:
    """ATM 1-year put, vol 20%, rate 5%, no dividend.
    Closed form ≈ 5.5735."""
    today = date(2025, 1, 1)
    params = OptionParams(
        spot=100.0, strike=100.0, rate=0.05, dividend=0.0,
        volatility=0.20, valuation=today, expiry=date(2026, 1, 1), right="put",
    )
    price = price_european_bs(params)
    assert price == pytest.approx(5.5735, abs=0.05)


def test_american_put_premium_over_european() -> None:
    """American put should be worth at least as much as European put."""
    today = date(2025, 1, 1)
    params = OptionParams(
        spot=100.0, strike=110.0, rate=0.05, dividend=0.0,
        volatility=0.20, valuation=today, expiry=date(2026, 1, 1), right="put",
    )
    eu = price_european_bs(params)
    am = price_american_binomial(params, steps=200)
    assert am >= eu - 1e-6


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
