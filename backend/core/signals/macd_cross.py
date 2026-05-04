"""MACD line / signal-line cross detector."""
from __future__ import annotations

from typing import Any

from core.indicators import compute_indicator
from core.signals.types import Signal


def detect_macd_crosses(
    bars: list[dict[str, Any]],
    *,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> list[Signal]:
    """Emit one Signal at each bar where the MACD line crosses the signal line.

    Bull cross: macd was below signal at bar i-1 and is above at bar i.
    Bear cross: macd was above signal at bar i-1 and is below at bar i.
    """
    if len(bars) < slow + signal_period:
        return []

    closes = [float(b.get("close") or 0.0) for b in bars]
    series_map = compute_indicator("macd", closes, params={
        "fast": fast, "slow": slow, "signal": signal_period,
    })
    macd_series = series_map.get("macd") or []
    signal_series = series_map.get("signal") or []
    if not macd_series or not signal_series:
        return []

    out: list[Signal] = []
    for i in range(1, len(bars)):
        if i >= len(macd_series) or i >= len(signal_series):
            break
        m_prev, m_curr = macd_series[i - 1], macd_series[i]
        s_prev, s_curr = signal_series[i - 1], signal_series[i]
        if m_prev is None or m_curr is None or s_prev is None or s_curr is None:
            continue

        prev_above = m_prev > s_prev
        curr_above = m_curr > s_curr
        if prev_above == curr_above:
            continue

        gap = abs(m_curr - s_curr)
        strength = max(0.0, min(1.0, gap / max(abs(closes[i]) * 0.01, 0.01)))
        kind = "macd_bull_cross" if curr_above else "macd_bear_cross"
        direction = "buy" if curr_above else "sell"
        ts = bars[i].get("timestamp")
        out.append(Signal(
            kind=kind, direction=direction, strength=strength,
            ts=ts, bar_index=i,
            interpretation=f"MACD {kind.replace('macd_', '').replace('_', ' ')} "
                           f"(macd={m_curr:.3f}, signal={s_curr:.3f})",
        ))
    return out
