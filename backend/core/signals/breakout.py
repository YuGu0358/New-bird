"""Pure range-breakout detector — close above 20-bar high or below 20-bar low."""
from __future__ import annotations

from typing import Any

from core.signals.types import Signal

LOOKBACK = 20


def detect_breakouts(bars: list[dict[str, Any]]) -> list[Signal]:
    """Emit a signal whenever today's close breaks above the prior 20-bar high
    or below the prior 20-bar low. Strength = % distance beyond the level."""
    if len(bars) <= LOOKBACK:
        return []
    out: list[Signal] = []
    for i in range(LOOKBACK, len(bars)):
        window = [float(bars[j].get("close") or 0.0) for j in range(i - LOOKBACK, i)]
        if not window:
            continue
        today = float(bars[i].get("close") or 0.0)
        prev_high = max(window)
        prev_low = min(window)
        if today > prev_high and prev_high > 0:
            pct = (today - prev_high) / prev_high
            out.append(Signal(
                kind="price_breakout_high", direction="buy",
                strength=min(1.0, pct * 20),
                ts=bars[i].get("timestamp"), bar_index=i,
                interpretation=f"Close {today:.2f} > 20d high {prev_high:.2f} (+{pct*100:.1f}%)",
            ))
        elif today < prev_low and prev_low > 0:
            pct = (prev_low - today) / prev_low
            out.append(Signal(
                kind="price_breakdown_low", direction="sell",
                strength=min(1.0, pct * 20),
                ts=bars[i].get("timestamp"), bar_index=i,
                interpretation=f"Close {today:.2f} < 20d low {prev_low:.2f} ({-pct*100:.1f}%)",
            ))
    return out
