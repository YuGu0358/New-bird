"""Unit tests for the valuation engine (DCF + PE channel)."""
from __future__ import annotations

import math

import pytest

from core.valuation import DCFInputs, compute_pe_channel, run_dcf


class TestDCF:
    def test_basic_fair_value_is_finite_and_positive(self) -> None:
        result = run_dcf(
            DCFInputs(
                fcfe0=10.0,
                growth_stage1=0.10,
                growth_terminal=0.025,
                discount_rate=0.10,
            )
        )
        assert result.fair_value_per_share > 0
        assert result.fair_low <= result.fair_value_per_share <= result.fair_high
        assert math.isfinite(result.fair_value_per_share)

    def test_higher_growth_lifts_fair_value(self) -> None:
        base = run_dcf(
            DCFInputs(fcfe0=10.0, growth_stage1=0.05, growth_terminal=0.025, discount_rate=0.10)
        )
        bull = run_dcf(
            DCFInputs(fcfe0=10.0, growth_stage1=0.15, growth_terminal=0.025, discount_rate=0.10)
        )
        assert bull.fair_value_per_share > base.fair_value_per_share

    def test_higher_discount_rate_lowers_fair_value(self) -> None:
        cheap = run_dcf(
            DCFInputs(fcfe0=10.0, growth_stage1=0.10, growth_terminal=0.025, discount_rate=0.08)
        )
        expensive = run_dcf(
            DCFInputs(fcfe0=10.0, growth_stage1=0.10, growth_terminal=0.025, discount_rate=0.12)
        )
        assert expensive.fair_value_per_share < cheap.fair_value_per_share

    def test_terminal_above_discount_raises(self) -> None:
        with pytest.raises(ValueError):
            run_dcf(
                DCFInputs(
                    fcfe0=10.0,
                    growth_stage1=0.10,
                    growth_terminal=0.12,
                    discount_rate=0.10,
                )
            )

    def test_grid_includes_low_and_high(self) -> None:
        result = run_dcf(
            DCFInputs(fcfe0=10.0, growth_stage1=0.10, growth_terminal=0.025, discount_rate=0.10)
        )
        # The 9-cell grid (3×3 ±1pt each axis) should be populated with > 0 cells.
        assert len(result.grid) > 0
        values = [g["fair_value"] for g in result.grid]
        assert min(values) == result.fair_low
        assert max(values) == result.fair_high


class TestPEChannel:
    def test_empty_inputs_returns_neutral_payload(self) -> None:
        out = compute_pe_channel(ticker="TEST", prices=[], eps_ttm=None)
        assert out.pe_p50 is None
        assert out.fair_p50 is None
        assert out.sample_size == 0

    def test_zero_eps_returns_no_bands(self) -> None:
        prices = [100.0, 101.0, 102.0]
        out = compute_pe_channel(ticker="TEST", prices=prices, eps_ttm=0)
        assert out.pe_p50 is None

    def test_percentiles_are_monotone(self) -> None:
        # 5 years of slightly trending prices, EPS ~ steady
        prices = [100 + i * 0.05 for i in range(252 * 5)]
        out = compute_pe_channel(ticker="TEST", prices=prices, eps_ttm=8.0)
        assert out.pe_p5 <= out.pe_p25 <= out.pe_p50 <= out.pe_p75 <= out.pe_p95
        assert out.fair_p5 <= out.fair_p25 <= out.fair_p50 <= out.fair_p75 <= out.fair_p95
        assert out.sample_size == len(prices)

    def test_current_pe_uses_last_price_when_unspecified(self) -> None:
        prices = [100.0, 110.0, 120.0]
        out = compute_pe_channel(ticker="TEST", prices=prices, eps_ttm=10.0)
        assert out.current_price == 120.0
        assert out.current_pe == pytest.approx(12.0)
