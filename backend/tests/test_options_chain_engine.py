"""Unit tests for the options-chain analytics engine."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.options_chain import (
    OptionContract,
    black_scholes_greeks,
    focus_expiry,
    scan_pinning,
    summarize_chain,
)


class TestBlackScholes:
    def test_atm_call_delta_near_half(self) -> None:
        g = black_scholes_greeks(spot=100, strike=100, time_to_expiry_yrs=0.25, iv=0.3)
        assert 0.5 < g.delta < 0.65  # slightly > 0.5 because of positive r

    def test_atm_put_delta_negative_near_minus_half(self) -> None:
        g = black_scholes_greeks(
            spot=100, strike=100, time_to_expiry_yrs=0.25, iv=0.3, option_type="P"
        )
        assert -0.5 < g.delta < 0  # slightly above −0.5

    def test_call_and_put_share_gamma(self) -> None:
        c = black_scholes_greeks(spot=100, strike=100, time_to_expiry_yrs=0.25, iv=0.3, option_type="C")
        p = black_scholes_greeks(spot=100, strike=100, time_to_expiry_yrs=0.25, iv=0.3, option_type="P")
        assert c.gamma == pytest.approx(p.gamma, rel=1e-9)

    def test_zero_inputs_return_none(self) -> None:
        assert black_scholes_greeks(spot=0, strike=100, time_to_expiry_yrs=0.25, iv=0.3) is None
        assert black_scholes_greeks(spot=100, strike=100, time_to_expiry_yrs=0, iv=0.3) is None
        assert black_scholes_greeks(spot=100, strike=100, time_to_expiry_yrs=0.25, iv=0) is None


class TestSummarizeChain:
    def _build(self, spot: float = 100.0) -> list[OptionContract]:
        exp = date.today() + timedelta(days=14)
        return [
            OptionContract(expiry=exp, strike=95, option_type="C", open_interest=500, volume=20, iv=0.3, delta=0.7, gamma=0.018),
            OptionContract(expiry=exp, strike=100, option_type="C", open_interest=2000, volume=200, iv=0.3, delta=0.5, gamma=0.025),
            OptionContract(expiry=exp, strike=110, option_type="C", open_interest=3000, volume=50, iv=0.3, delta=0.3, gamma=0.02),
            OptionContract(expiry=exp, strike=90, option_type="P", open_interest=2500, volume=80, iv=0.3, delta=-0.4, gamma=0.022),
            OptionContract(expiry=exp, strike=85, option_type="P", open_interest=1000, volume=10, iv=0.3, delta=-0.25, gamma=0.015),
        ]

    def test_call_wall_above_spot(self) -> None:
        s = summarize_chain(ticker="TEST", spot=100.0, contracts=self._build())
        assert s is not None
        assert s.call_wall is not None and s.call_wall >= 100.0

    def test_put_wall_below_spot(self) -> None:
        s = summarize_chain(ticker="TEST", spot=100.0, contracts=self._build())
        assert s is not None
        assert s.put_wall is not None and s.put_wall <= 100.0

    def test_total_gex_is_sum_of_call_and_put(self) -> None:
        s = summarize_chain(ticker="TEST", spot=100.0, contracts=self._build())
        assert s is not None
        assert s.total_gex == pytest.approx(s.call_gex_total + s.put_gex_total, rel=1e-9)

    def test_max_pain_returned(self) -> None:
        s = summarize_chain(ticker="TEST", spot=100.0, contracts=self._build())
        assert s is not None
        assert s.max_pain is not None

    def test_empty_chain_returns_none(self) -> None:
        s = summarize_chain(ticker="TEST", spot=100.0, contracts=[])
        assert s is None


class TestExpiryFocus:
    def _build(self, exp_offset_days: int = 14) -> tuple[date, list[OptionContract]]:
        exp = date(2026, 5, 1) + timedelta(days=exp_offset_days)
        rows = [
            OptionContract(expiry=exp, strike=95,  option_type="C", open_interest=500, volume=20, iv=0.30, delta=0.7,  gamma=0.018),
            OptionContract(expiry=exp, strike=100, option_type="C", open_interest=2000, volume=200, iv=0.30, delta=0.5, gamma=0.025),
            OptionContract(expiry=exp, strike=105, option_type="C", open_interest=2500, volume=300, iv=0.30, delta=0.4, gamma=0.022),
            OptionContract(expiry=exp, strike=110, option_type="C", open_interest=3000, volume=50,  iv=0.30, delta=0.3, gamma=0.020),
            OptionContract(expiry=exp, strike=100, option_type="P", open_interest=1000, volume=80, iv=0.30, delta=-0.5, gamma=0.025),
            OptionContract(expiry=exp, strike=95,  option_type="P", open_interest=2500, volume=80, iv=0.30, delta=-0.4, gamma=0.022),
            OptionContract(expiry=exp, strike=90,  option_type="P", open_interest=3500, volume=10, iv=0.30, delta=-0.3, gamma=0.018),
        ]
        return exp, rows

    def test_expected_move_present_with_iv(self) -> None:
        exp, rows = self._build()
        focus = focus_expiry(ticker="TEST", spot=100.0, contracts=rows, expiry=exp, today=exp - timedelta(days=14))
        assert focus is not None
        assert focus.atm_iv is not None
        assert focus.expected_move is not None
        assert focus.expected_low < 100 < focus.expected_high

    def test_top_calls_are_above_spot_and_sorted_by_oi(self) -> None:
        exp, rows = self._build()
        focus = focus_expiry(ticker="TEST", spot=100.0, contracts=rows, expiry=exp, top_n=3, today=exp - timedelta(days=14))
        assert focus is not None
        for s in focus.top_call_strikes:
            assert s.strike > 100.0
        ois = [s.open_interest for s in focus.top_call_strikes]
        assert ois == sorted(ois, reverse=True)

    def test_top_puts_are_below_spot_and_sorted(self) -> None:
        exp, rows = self._build()
        focus = focus_expiry(ticker="TEST", spot=100.0, contracts=rows, expiry=exp, top_n=3, today=exp - timedelta(days=14))
        assert focus is not None
        for s in focus.top_put_strikes:
            assert s.strike < 100.0
        ois = [s.open_interest for s in focus.top_put_strikes]
        assert ois == sorted(ois, reverse=True)

    def test_put_call_oi_ratio_is_meaningful(self) -> None:
        exp, rows = self._build()
        focus = focus_expiry(ticker="TEST", spot=100.0, contracts=rows, expiry=exp, today=exp - timedelta(days=14))
        assert focus is not None
        assert focus.put_call_oi_ratio is not None
        assert focus.put_call_oi_ratio == pytest.approx(focus.total_put_oi / focus.total_call_oi, rel=1e-9)

    def test_no_match_for_unknown_expiry_returns_none(self) -> None:
        _exp, rows = self._build()
        wrong_exp = date(2030, 1, 1)
        assert focus_expiry(ticker="TEST", spot=100.0, contracts=rows, expiry=wrong_exp) is None


class TestFridayScan:
    """Pinning scanner — verify the score components fire as expected."""

    def _strong_setup(self) -> tuple[date, list[OptionContract]]:
        # Spot=100, walls 95/105 (within 5% → triggers <2% only on closer side),
        # huge OI cluster on both walls (concentration + salience high), DTE=1.
        exp = date.today() + timedelta(days=1)
        return exp, [
            # Massive call wall at 105 (just above spot)
            OptionContract(expiry=exp, strike=105, option_type="C", open_interest=50000, volume=1000, iv=0.20, delta=0.4, gamma=0.04),
            # Filler call OI at the other strikes — keep median low so 105 is salient
            OptionContract(expiry=exp, strike=110, option_type="C", open_interest=200, volume=10, iv=0.20, delta=0.2, gamma=0.025),
            OptionContract(expiry=exp, strike=115, option_type="C", open_interest=200, volume=10, iv=0.20, delta=0.1, gamma=0.018),
            # Massive put wall at 95
            OptionContract(expiry=exp, strike=95,  option_type="P", open_interest=50000, volume=1000, iv=0.20, delta=-0.4, gamma=0.04),
            OptionContract(expiry=exp, strike=90,  option_type="P", open_interest=200,  volume=10, iv=0.20, delta=-0.2, gamma=0.025),
            OptionContract(expiry=exp, strike=85,  option_type="P", open_interest=200,  volume=10, iv=0.20, delta=-0.1, gamma=0.018),
        ]

    def test_strong_pinning_setup_scores_high(self) -> None:
        exp, rows = self._strong_setup()
        scan = scan_pinning(ticker="TEST", spot=100.0, contracts=rows, target_expiry=exp)
        assert scan.has_data is True
        assert scan.verdict in {"BET", "MIXED"}
        # spot fenced + strong concentration + salience + DTE=1 should easily score ≥40
        assert scan.pinning_score >= 40
        # Reasons should include the geometry hit
        assert any("fenced" in r.lower() for r in scan.reasons)

    def test_no_data_returns_zero_score(self) -> None:
        scan = scan_pinning(
            ticker="TEST",
            spot=100.0,
            contracts=[],
            target_expiry=date.today() + timedelta(days=1),
        )
        assert scan.has_data is False
        assert scan.pinning_score == 0
        assert scan.verdict == "SKIP"

    def test_zero_spot_returns_zero_score(self) -> None:
        exp, rows = self._strong_setup()
        scan = scan_pinning(ticker="TEST", spot=0.0, contracts=rows, target_expiry=exp)
        assert scan.has_data is False
        assert scan.pinning_score == 0

    def test_walls_picked_correctly(self) -> None:
        exp, rows = self._strong_setup()
        scan = scan_pinning(ticker="TEST", spot=100.0, contracts=rows, target_expiry=exp)
        assert scan.call_wall.strike == 105
        assert scan.put_wall.strike == 95
        # Both walls should have non-zero concentration/salience
        assert (scan.call_wall.concentration_pct or 0) > 0
        assert (scan.put_wall.concentration_pct or 0) > 0

    def test_adv_pressure_check_fires_when_provided(self) -> None:
        # Asymmetric chain — heavy call side, light put side, so total GEX
        # doesn't cancel to 0 (which would make the pressure calc moot).
        exp = date.today() + timedelta(days=1)
        rows = [
            OptionContract(expiry=exp, strike=105, option_type="C", open_interest=50000, volume=1000, iv=0.20, delta=0.4, gamma=0.04),
            OptionContract(expiry=exp, strike=95,  option_type="P", open_interest=100,   volume=10,   iv=0.20, delta=-0.4, gamma=0.04),
        ]
        small_adv = 1.0  # $1 ADV is impossibly small but proves the lever fires
        scan = scan_pinning(
            ticker="TEST", spot=100.0, contracts=rows, target_expiry=exp, adv_dollar=small_adv
        )
        assert scan.friday_gex_pressure_pct is not None and scan.friday_gex_pressure_pct > 10
        # Pressure-driven reason line should be present
        assert any("ADV" in r or "GEX" in r.upper() for r in scan.reasons)
