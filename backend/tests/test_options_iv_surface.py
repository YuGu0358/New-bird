"""Unit tests for the IV surface module.

Pure compute; tests build hand-crafted OptionContract lists and verify the
exact arithmetic of the strike x expiry IV grid + per-expiry term-structure
summaries (ATM IV, 25-delta skew).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from core.options_chain import OptionContract, build_iv_surface


TODAY = date(2026, 4, 28)


def _row(
    *,
    expiry: date = date(2026, 6, 19),
    strike: float,
    side: str,
    oi: int = 100,
    iv: float | None = 0.30,
    delta: float | None = 0.5,
) -> OptionContract:
    return OptionContract(
        expiry=expiry,
        strike=strike,
        option_type=side,
        open_interest=oi,
        volume=0,
        iv=iv,
        delta=delta,
        gamma=0.01,
    )


def test_build_iv_surface_raises_on_non_positive_spot():
    """Pure compute should reject spot <= 0 loudly."""
    rows = [_row(expiry=date(2026, 5, 15), strike=100, side="C", oi=1000, iv=0.30, delta=0.50)]
    with pytest.raises(ValueError, match="spot > 0"):
        build_iv_surface(ticker="X", spot=0, contracts=rows, today=TODAY)
    with pytest.raises(ValueError, match="spot > 0"):
        build_iv_surface(ticker="X", spot=-1, contracts=rows, today=TODAY)


def test_empty_chain_returns_empty_surface():
    """No contracts → empty expiries + empty strikes; spot still echoed."""
    out = build_iv_surface(ticker="AAPL", spot=150.0, contracts=[], today=TODAY)
    assert out.ticker == "AAPL"
    assert out.spot == 150.0
    assert out.expiries == []
    assert out.strikes == []
    assert out.as_of == TODAY


def test_single_expiry_three_strikes_calls_only():
    """3 calls at 100/105/110, spot=100 → moneyness 0.0, 0.05, 0.10."""
    exp = date(2026, 6, 19)
    rows = [
        _row(expiry=exp, strike=100, side="C", iv=0.30, oi=10),
        _row(expiry=exp, strike=105, side="C", iv=0.32, oi=20),
        _row(expiry=exp, strike=110, side="C", iv=0.35, oi=30),
    ]
    out = build_iv_surface(ticker="AAPL", spot=100.0, contracts=rows, today=TODAY)

    assert len(out.expiries) == 1
    e = out.expiries[0]
    assert e.expiry == exp
    assert [p.strike for p in e.points] == [100, 105, 110]
    assert [p.iv for p in e.points] == [0.30, 0.32, 0.35]
    # moneyness = (strike - spot) / spot, exact arithmetic.
    assert e.points[0].moneyness == 0.0
    assert e.points[1].moneyness == pytest.approx(0.05)
    assert e.points[2].moneyness == pytest.approx(0.10)
    # Calls only.
    for p in e.points:
        assert p.has_call is True
        assert p.has_put is False
    assert out.strikes == [100, 105, 110]


def test_call_iv_preferred_over_put_iv_at_same_strike():
    """Both call+put have IV at the same row → grid uses call IV."""
    exp = date(2026, 6, 19)
    rows = [
        _row(expiry=exp, strike=100, side="C", iv=0.30, delta=0.5),
        _row(expiry=exp, strike=100, side="P", iv=0.45, delta=-0.5),
    ]
    out = build_iv_surface(ticker="AAPL", spot=100.0, contracts=rows, today=TODAY)
    assert len(out.expiries) == 1
    pts = out.expiries[0].points
    assert len(pts) == 1
    assert pts[0].iv == 0.30  # call IV preferred
    assert pts[0].has_call is True
    assert pts[0].has_put is True


def test_put_iv_used_when_call_iv_missing_or_nan():
    """Call IV None or NaN → fall back to put IV; flags reflect presence."""
    exp = date(2026, 6, 19)
    rows = [
        # Strike 100: call IV None → put IV used.
        _row(expiry=exp, strike=100, side="C", iv=None, delta=0.5),
        _row(expiry=exp, strike=100, side="P", iv=0.42, delta=-0.5),
        # Strike 105: call IV NaN → put IV used.
        _row(expiry=exp, strike=105, side="C", iv=float("nan"), delta=0.5),
        _row(expiry=exp, strike=105, side="P", iv=0.40, delta=-0.5),
        # Strike 110: only a put, no call at all.
        _row(expiry=exp, strike=110, side="P", iv=0.50, delta=-0.4),
    ]
    out = build_iv_surface(ticker="AAPL", spot=100.0, contracts=rows, today=TODAY)
    pts = out.expiries[0].points
    by_strike = {p.strike: p for p in pts}

    assert by_strike[100].iv == 0.42
    assert by_strike[100].has_call is True  # call row exists, just IV is missing
    assert by_strike[100].has_put is True

    assert by_strike[105].iv == 0.40
    assert by_strike[105].has_call is True
    assert by_strike[105].has_put is True

    assert by_strike[110].iv == 0.50
    assert by_strike[110].has_call is False  # no call row
    assert by_strike[110].has_put is True


def test_atm_iv_picks_strike_closest_to_spot():
    """ATM = strike closest to spot; tie-break: lower strike."""
    exp = date(2026, 6, 19)
    # Case A: spot=102, strikes=[100, 105]; |100-102|=2 < |105-102|=3 → 100.
    rows_a = [
        _row(expiry=exp, strike=100, side="C", iv=0.30),
        _row(expiry=exp, strike=105, side="C", iv=0.40),
    ]
    out_a = build_iv_surface(ticker="X", spot=102.0, contracts=rows_a, today=TODAY)
    assert out_a.expiries[0].atm_iv == 0.30  # IV at strike 100

    # Case B: spot=103, strikes=[100, 105]; |100-103|=3 vs |105-103|=2 → 105.
    rows_b = [
        _row(expiry=exp, strike=100, side="C", iv=0.30),
        _row(expiry=exp, strike=105, side="C", iv=0.40),
    ]
    out_b = build_iv_surface(ticker="X", spot=103.0, contracts=rows_b, today=TODAY)
    assert out_b.expiries[0].atm_iv == 0.40  # IV at strike 105

    # Case C: tie — spot=102.5 with strikes [100, 105]; both are 2.5 away.
    # Tie-break: lower strike wins → 100.
    rows_c = [
        _row(expiry=exp, strike=100, side="C", iv=0.30),
        _row(expiry=exp, strike=105, side="C", iv=0.40),
    ]
    out_c = build_iv_surface(ticker="X", spot=102.5, contracts=rows_c, today=TODAY)
    assert out_c.expiries[0].atm_iv == 0.30  # tie → lower strike


def test_skew_pct_uses_25_delta_call_and_put_iv_difference():
    """call delta=+0.25 IV=0.30, put delta=-0.25 IV=0.40 → skew = 0.10."""
    exp = date(2026, 6, 19)
    rows = [
        # Calls: delta values 0.5, 0.25, 0.10. 0.25 IV is 0.30.
        _row(expiry=exp, strike=100, side="C", iv=0.20, delta=0.50),
        _row(expiry=exp, strike=110, side="C", iv=0.30, delta=0.25),
        _row(expiry=exp, strike=120, side="C", iv=0.35, delta=0.10),
        # Puts: delta values -0.5, -0.25, -0.10. -0.25 IV is 0.40.
        _row(expiry=exp, strike=100, side="P", iv=0.22, delta=-0.50),
        _row(expiry=exp, strike=90, side="P", iv=0.40, delta=-0.25),
        _row(expiry=exp, strike=80, side="P", iv=0.50, delta=-0.10),
    ]
    out = build_iv_surface(ticker="X", spot=100.0, contracts=rows, today=TODAY)
    skew = out.expiries[0].skew_pct
    assert skew is not None
    assert skew == pytest.approx(0.10)


def test_skew_pct_none_when_either_25_delta_side_missing():
    """Calls only → no -25-delta put → skew is None."""
    exp = date(2026, 6, 19)
    rows = [
        _row(expiry=exp, strike=100, side="C", iv=0.30, delta=0.50),
        _row(expiry=exp, strike=110, side="C", iv=0.32, delta=0.25),
    ]
    out = build_iv_surface(ticker="X", spot=100.0, contracts=rows, today=TODAY)
    assert out.expiries[0].skew_pct is None


def test_multiple_expiries_sorted_dte_correct_strikes_union():
    """Expiries sorted ascending; dte = (expiry - today).days; strikes union."""
    near = date(2026, 5, 15)   # 17 days from TODAY=2026-04-28
    far = date(2026, 9, 18)    # 143 days
    rows = [
        # Far expiry first in input.
        _row(expiry=far, strike=110, side="C", iv=0.28),
        _row(expiry=far, strike=120, side="C", iv=0.30),
        _row(expiry=near, strike=100, side="C", iv=0.35),
        _row(expiry=near, strike=110, side="C", iv=0.36),
    ]
    out = build_iv_surface(ticker="X", spot=105.0, contracts=rows, today=TODAY)
    assert [e.expiry for e in out.expiries] == [near, far]
    assert out.expiries[0].dte == (near - TODAY).days
    assert out.expiries[1].dte == (far - TODAY).days
    # Union of every strike that has a point anywhere.
    assert out.strikes == [100, 110, 120]


def test_non_positive_or_nan_or_none_iv_rows_skipped():
    """iv=0, iv=NaN, iv=None on both sides → no point at that strike."""
    exp = date(2026, 6, 19)
    rows = [
        # Strike 100: usable call IV → point exists.
        _row(expiry=exp, strike=100, side="C", iv=0.30),
        # Strike 105: call iv=0, no put → skipped.
        _row(expiry=exp, strike=105, side="C", iv=0.0),
        # Strike 110: call iv=NaN, put iv=NaN → skipped.
        _row(expiry=exp, strike=110, side="C", iv=float("nan")),
        _row(expiry=exp, strike=110, side="P", iv=float("nan")),
        # Strike 115: both sides iv=None → skipped.
        _row(expiry=exp, strike=115, side="C", iv=None),
        _row(expiry=exp, strike=115, side="P", iv=None),
        # Strike 120: call iv=-0.1 (non-positive), no put → skipped.
        _row(expiry=exp, strike=120, side="C", iv=-0.10),
    ]
    out = build_iv_surface(ticker="X", spot=100.0, contracts=rows, today=TODAY)
    pts = out.expiries[0].points
    assert [p.strike for p in pts] == [100]
    assert out.strikes == [100]


def test_determinism():
    """Same input → identical surface (no hidden state, no ordering tricks)."""
    near = date(2026, 5, 15)
    far = date(2026, 9, 18)
    rows = [
        _row(expiry=far, strike=110, side="C", iv=0.28, delta=0.4),
        _row(expiry=far, strike=120, side="C", iv=0.30, delta=0.25),
        _row(expiry=near, strike=100, side="C", iv=0.35, delta=0.5),
        _row(expiry=near, strike=110, side="C", iv=0.36, delta=0.25),
        _row(expiry=near, strike=90, side="P", iv=0.40, delta=-0.25),
    ]
    a = build_iv_surface(ticker="X", spot=105.0, contracts=rows, today=TODAY)
    b = build_iv_surface(
        ticker="X",
        spot=105.0,
        contracts=[replace(r) for r in rows],
        today=TODAY,
    )
    assert a.strikes == b.strikes
    assert [e.expiry for e in a.expiries] == [e.expiry for e in b.expiries]
    for ea, eb in zip(a.expiries, b.expiries):
        assert ea.points == eb.points
        assert ea.atm_iv == eb.atm_iv
        # skew may be None for a given expiry — equal None is still equal.
        assert ea.skew_pct == eb.skew_pct
        assert ea.dte == eb.dte
