"""Tests for the pure-Python technical indicators.

Reference values pinned from numpy / TA-Lib equivalents so future "drive-by
improvements" can't silently shift the math.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services import chart_service, indicators_service
from core.indicators import bbands, compute_indicator, ema, macd, rsi, sma


# ---------- SMA ----------


def test_sma_basic_known_values():
    """SMA(3) of [1,2,3,4,5,6] = [None, None, 2, 3, 4, 5]."""
    out = sma([1, 2, 3, 4, 5, 6], period=3)
    assert out == [None, None, 2.0, 3.0, 4.0, 5.0]


def test_sma_handles_short_series():
    out = sma([1, 2], period=5)
    assert out == [None, None]


def test_sma_rejects_zero_or_negative_period():
    with pytest.raises(ValueError, match="period must be > 0"):
        sma([1, 2, 3], period=0)


# ---------- EMA ----------


def test_ema_seed_matches_sma():
    """First EMA value should equal SMA of the seed window."""
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    out = ema(values, period=5)
    # First 4 → None; out[4] = SMA(values[0:5]) = 3.0
    assert out[:4] == [None] * 4
    assert out[4] == pytest.approx(3.0)
    # Subsequent values use α=2/(5+1)=1/3
    expected_5 = (1 / 3) * 6 + (2 / 3) * 3.0
    assert out[5] == pytest.approx(expected_5)


def test_ema_smaller_than_period_returns_all_none():
    assert ema([1, 2, 3], period=5) == [None] * 3


# ---------- RSI ----------


def test_rsi_pure_uptrend_returns_100():
    """A monotonically increasing series has zero losses → RSI = 100."""
    values = list(range(1, 30))  # 29 strictly increasing closes
    out = rsi(values, period=14)
    assert out[:14] == [None] * 14
    for v in out[14:]:
        assert v == pytest.approx(100.0)


def test_rsi_pure_downtrend_returns_zero():
    values = list(range(30, 1, -1))
    out = rsi(values, period=14)
    for v in out[14:]:
        assert v == pytest.approx(0.0)


def test_rsi_known_reference_value():
    """Hand-checked RSI(2) on a tiny series.

    Closes: [10, 11, 12, 11, 10]
    deltas: [+1, +1, -1, -1]
    period=2:
      i=2 (after seeding on closes[0..2]): avg_gain=(1+1)/2=1.0, avg_loss=0/2=0
        → RSI = 100 (no losses)
      i=3 (delta=-1): avg_gain=(1.0*1+0)/2=0.5, avg_loss=(0.0*1+1)/2=0.5
        → RS=1, RSI=50
      i=4 (delta=-1): avg_gain=(0.5*1+0)/2=0.25, avg_loss=(0.5*1+1)/2=0.75
        → RS=1/3, RSI = 100 - 100/(1+1/3) = 25
    """
    out = rsi([10, 11, 12, 11, 10], period=2)
    assert out[0] is None
    assert out[1] is None
    assert out[2] == pytest.approx(100.0)
    assert out[3] == pytest.approx(50.0)
    assert out[4] == pytest.approx(25.0)


# ---------- MACD ----------


def test_macd_returns_three_aligned_series():
    values = [float(i) for i in range(1, 60)]  # smooth ramp
    macd_line, signal_line, histogram = macd(values)
    assert len(macd_line) == len(signal_line) == len(histogram) == len(values)
    # macd_line is None until BOTH EMAs are seeded → index 25 (slow=26).
    for i in range(25):
        assert macd_line[i] is None
    assert macd_line[25] is not None
    # signal_line starts a further (signal=9 - 1) bars after macd_line.
    assert signal_line[25 + 8] is not None


def test_macd_validates_window_relationship():
    """fast must be < slow; otherwise ValueError."""
    with pytest.raises(ValueError, match="fast must be"):
        macd([1.0, 2.0, 3.0], fast=26, slow=12, signal=9)


def test_macd_histogram_is_macd_minus_signal():
    values = [float(i) for i in range(1, 80)]
    m, s, h = macd(values)
    for mi, si, hi in zip(m, s, h):
        if mi is None or si is None:
            assert hi is None
        else:
            assert hi == pytest.approx(mi - si)


# ---------- BBANDS ----------


def test_bbands_constant_series_has_zero_width():
    """Zero variance → upper == middle == lower."""
    values = [100.0] * 30
    upper, middle, lower = bbands(values, period=20, k=2.0)
    for u, m, l in zip(upper[19:], middle[19:], lower[19:]):
        assert u == pytest.approx(100.0)
        assert m == pytest.approx(100.0)
        assert l == pytest.approx(100.0)


def test_bbands_uses_sample_stdev():
    """SMA(5) on [1,2,3,4,5] = 3; sample stdev = sqrt(10/4) = sqrt(2.5).
    Upper at k=2 should be 3 + 2*sqrt(2.5) ≈ 6.162."""
    import math

    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    upper, middle, lower = bbands(values, period=5, k=2.0)
    assert middle[4] == pytest.approx(3.0)
    expected_upper = 3.0 + 2.0 * math.sqrt(2.5)
    assert upper[4] == pytest.approx(expected_upper)
    assert lower[4] == pytest.approx(3.0 - 2.0 * math.sqrt(2.5))


def test_bbands_rejects_period_one():
    """period must be >1 for sample stdev (n-1 in denominator)."""
    with pytest.raises(ValueError, match="period must be > 1"):
        bbands([1.0, 2.0], period=1)


# ---------- Dispatcher ----------


def test_compute_indicator_dispatch_unknown_raises():
    with pytest.raises(ValueError, match="Unknown indicator"):
        compute_indicator("nonsense", [1.0, 2.0, 3.0])


def test_compute_indicator_overrides_default_params():
    out = compute_indicator("sma", [1, 2, 3, 4, 5], params={"period": 2})
    # SMA(2): [None, 1.5, 2.5, 3.5, 4.5]
    assert out["value"][0] is None
    assert out["value"][1] == pytest.approx(1.5)
    assert out["value"][4] == pytest.approx(4.5)


def test_compute_indicator_macd_returns_three_keys():
    out = compute_indicator("macd", [float(i) for i in range(1, 50)])
    assert set(out.keys()) == {"macd", "signal", "histogram"}


def test_compute_indicator_bbands_returns_three_keys():
    out = compute_indicator("bbands", [float(i) for i in range(1, 30)])
    assert set(out.keys()) == {"upper", "middle", "lower"}


# ---------- Service (with chart_service mocked) ----------


class IndicatorServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        chart_service._chart_cache.clear()  # noqa: SLF001

    async def test_compute_for_symbol_pulls_chart_and_runs_indicator(self) -> None:
        chart_payload = {
            "symbol": "NVDA",
            "range": "1mo",
            "interval": "1d",
            "latest_price": 110.0,
            "range_change_percent": 5.0,
            "points": [
                {
                    "timestamp": datetime(2026, 4, 1 + i, tzinfo=timezone.utc),
                    "open": 100.0 + i,
                    "high": 102.0 + i,
                    "low": 99.0 + i,
                    "close": 100.0 + i,
                    "volume": 1000,
                }
                for i in range(20)
            ],
        }

        with patch.object(
            chart_service, "get_symbol_chart", return_value=chart_payload
        ):
            payload = await indicators_service.compute_for_symbol(
                "NVDA", name="sma", params={"period": 5}
            )

        self.assertEqual(payload["symbol"], "NVDA")
        self.assertEqual(payload["indicator"], "sma")
        self.assertEqual(payload["params"]["period"], 5)
        self.assertEqual(len(payload["timestamps"]), 20)
        self.assertEqual(len(payload["series"]["value"]), 20)
        # SMA(5) on a strict ramp 100..119 → at index 4 = mean(100..104) = 102
        self.assertAlmostEqual(payload["series"]["value"][4], 102.0)

    async def test_compute_for_symbol_rejects_unknown_indicator(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown indicator"):
            await indicators_service.compute_for_symbol("NVDA", name="bogus")
