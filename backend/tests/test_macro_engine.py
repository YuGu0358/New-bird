"""Unit tests for the macro engine (threshold + FRED helpers + seed list)."""
from __future__ import annotations

from datetime import date, timedelta

from core.macro import SEED_INDICATORS, evaluate_signal
from core.macro.fred import FREDObservation, yoy_pct_change


class TestThresholdEngine:
    def test_none_value_is_neutral(self) -> None:
        assert evaluate_signal(None, {"direction": "higher_is_worse", "ok_max": 1, "warn_max": 2, "danger_max": 3}) == "neutral"

    def test_informational_is_neutral(self) -> None:
        assert evaluate_signal(42.0, {"direction": "informational"}) == "neutral"

    def test_higher_is_worse_levels(self) -> None:
        spec = {"ok_max": 4.0, "warn_max": 5.5, "danger_max": 7.0, "direction": "higher_is_worse"}
        assert evaluate_signal(3.0, spec) == "ok"
        assert evaluate_signal(5.0, spec) == "warn"
        assert evaluate_signal(6.5, spec) == "danger"
        assert evaluate_signal(8.0, spec) == "danger"

    def test_higher_is_better_levels(self) -> None:
        # Yield-curve style: warn_max=0.5 means OK when value >= 0.5, WARN when value >= 0.0
        spec = {"ok_max": 0.0, "warn_max": 0.5, "danger_max": 999.0, "direction": "higher_is_better"}
        assert evaluate_signal(1.0, spec) == "ok"
        assert evaluate_signal(0.3, spec) == "warn"
        assert evaluate_signal(-0.5, spec) == "danger"

    def test_missing_thresholds_is_neutral(self) -> None:
        assert evaluate_signal(1.0, {"direction": "higher_is_worse"}) == "neutral"


class TestSeedList:
    def test_seed_codes_are_unique(self) -> None:
        codes = [s.code for s in SEED_INDICATORS]
        assert len(set(codes)) == len(codes)

    def test_at_least_four_ensemble_core(self) -> None:
        core = [s for s in SEED_INDICATORS if s.is_ensemble_core]
        assert len(core) >= 4

    def test_each_indicator_has_i18n_keys(self) -> None:
        for s in SEED_INDICATORS:
            assert s.i18n_key
            assert s.description_key


class TestYoYPct:
    def test_constant_series_yields_zero(self) -> None:
        today = date.today()
        obs = [FREDObservation(series_id="X", as_of=today - timedelta(days=365 * i), value=100.0) for i in range(5)]
        result = yoy_pct_change(obs)
        assert result  # at least one row
        for r in result:
            assert abs(r.value) < 1e-9

    def test_doubling_yields_100pct(self) -> None:
        today = date.today()
        # year 0 = 100, year 1 = 200, year 2 = 400 — each YoY = +100%
        obs = [
            FREDObservation(series_id="X", as_of=today - timedelta(days=365 * 2), value=100.0),
            FREDObservation(series_id="X", as_of=today - timedelta(days=365), value=200.0),
            FREDObservation(series_id="X", as_of=today, value=400.0),
        ]
        result = yoy_pct_change(obs)
        # Both year-1 and year-2 entries should have +100%
        assert len(result) >= 1
        for r in result:
            assert abs(r.value - 100.0) < 1e-6

    def test_empty_input_returns_empty(self) -> None:
        assert yoy_pct_change([]) == []
