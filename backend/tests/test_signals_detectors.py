"""Pure-compute tests for signal detectors. No I/O, no fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _make_bars(closes: list[float], volumes: list[int] | None = None) -> list[dict]:
    out = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i, c in enumerate(closes):
        out.append({
            "timestamp": base + timedelta(days=i),
            "open": c, "high": c * 1.01, "low": c * 0.99,
            "close": c,
            "volume": (volumes[i] if volumes else 1_000_000),
        })
    return out


def test_macd_bull_and_bear_crosses_detected_on_oscillation() -> None:
    """One trough + one peak in the ramp guarantees a bull cross then bear cross."""
    from core.signals.macd_cross import detect_macd_crosses
    closes = (
        [100.0] * 20
        + [100 + 2 * i for i in range(15)]   # ramp up
        + [130 - 2 * i for i in range(20)]   # crash
        + [90 + 2 * i for i in range(15)]    # rebound
    )
    bars = _make_bars(closes)
    sigs = detect_macd_crosses(bars)
    bull = [s for s in sigs if s.kind == "macd_bull_cross"]
    bear = [s for s in sigs if s.kind == "macd_bear_cross"]
    assert bull, "expected at least one bull cross on the rebound"
    assert bear, "expected at least one bear cross on the crash"


def test_macd_no_cross_on_flat_series() -> None:
    from core.signals.macd_cross import detect_macd_crosses
    bars = _make_bars([100.0] * 60)
    sigs = detect_macd_crosses(bars)
    assert sigs == []


def test_rsi_oversold_bounce_emits_buy() -> None:
    from core.signals.rsi_levels import detect_rsi_signals
    closes = [100.0] * 14 + [100 - i for i in range(15)] + [85 + i * 0.8 for i in range(15)]
    bars = _make_bars(closes)
    sigs = detect_rsi_signals(bars)
    assert any(s.kind == "rsi_oversold_bounce" and s.direction == "buy" for s in sigs)


def test_rsi_overbought_fade_emits_sell() -> None:
    from core.signals.rsi_levels import detect_rsi_signals
    closes = [100.0] * 14 + [100 + i for i in range(15)] + [115 - i * 0.8 for i in range(15)]
    bars = _make_bars(closes)
    sigs = detect_rsi_signals(bars)
    assert any(s.kind == "rsi_overbought_fade" and s.direction == "sell" for s in sigs)


def test_rsi_no_signal_on_neutral_series() -> None:
    from core.signals.rsi_levels import detect_rsi_signals
    closes = [100 + (i % 3) for i in range(60)]
    bars = _make_bars(closes)
    sigs = detect_rsi_signals(bars)
    assert sigs == []


def test_volume_breakout_when_close_breaks_high_with_high_volume() -> None:
    from core.signals.volume_confirmation import detect_volume_signals
    closes = [100.0] * 20 + [105.0]
    volumes = [1_000_000] * 20 + [3_000_000]
    bars = _make_bars(closes, volumes)
    sigs = detect_volume_signals(bars)
    assert any(s.kind == "volume_breakout" and s.direction == "buy" for s in sigs)


def test_no_volume_breakout_on_low_volume_breakout() -> None:
    from core.signals.volume_confirmation import detect_volume_signals
    closes = [100.0] * 20 + [105.0]
    volumes = [1_000_000] * 21
    bars = _make_bars(closes, volumes)
    sigs = detect_volume_signals(bars)
    assert sigs == []


def test_breakout_high_signal_on_close_above_20d_high() -> None:
    from core.signals.breakout import detect_breakouts
    closes = [100.0] * 20 + [110.0]
    bars = _make_bars(closes)
    sigs = detect_breakouts(bars)
    assert any(s.kind == "price_breakout_high" and s.direction == "buy" for s in sigs)


def test_breakdown_low_signal_on_close_below_20d_low() -> None:
    from core.signals.breakout import detect_breakouts
    closes = [100.0] * 20 + [90.0]
    bars = _make_bars(closes)
    sigs = detect_breakouts(bars)
    assert any(s.kind == "price_breakdown_low" and s.direction == "sell" for s in sigs)
