"""Volume confirmation detector — flags price moves that are real (vol > 1.5x avg)."""
from __future__ import annotations

from typing import Any

from core.signals.types import Signal

VOLUME_MULTIPLIER = 1.5
LOOKBACK = 20


def detect_volume_signals(bars: list[dict[str, Any]]) -> list[Signal]:
    """Emit a signal when today's close exceeds the 20-bar high (or breaks low)
    AND volume is at least 1.5x the 20-bar average.
    """
    if len(bars) <= LOOKBACK:
        return []

    out: list[Signal] = []
    for i in range(LOOKBACK, len(bars)):
        window_closes = [float(bars[j].get("close") or 0.0) for j in range(i - LOOKBACK, i)]
        window_vols = [int(bars[j].get("volume") or 0) for j in range(i - LOOKBACK, i)]
        today_close = float(bars[i].get("close") or 0.0)
        today_vol = int(bars[i].get("volume") or 0)
        if not window_closes or sum(window_vols) == 0:
            continue

        avg_vol = sum(window_vols) / len(window_vols)
        if avg_vol <= 0 or today_vol < avg_vol * VOLUME_MULTIPLIER:
            continue

        prev_high = max(window_closes)
        prev_low = min(window_closes)
        ratio = today_vol / avg_vol

        if today_close > prev_high:
            out.append(Signal(
                kind="volume_breakout", direction="buy",
                strength=min(1.0, (ratio - 1.0) / 2.0),
                ts=bars[i].get("timestamp"), bar_index=i,
                interpretation=f"Close {today_close:.2f} > 20d high {prev_high:.2f} on {ratio:.1f}x avg volume",
            ))
        elif today_close < prev_low:
            out.append(Signal(
                kind="volume_breakdown", direction="sell",
                strength=min(1.0, (ratio - 1.0) / 2.0),
                ts=bars[i].get("timestamp"), bar_index=i,
                interpretation=f"Close {today_close:.2f} < 20d low {prev_low:.2f} on {ratio:.1f}x avg volume",
            ))
    return out
