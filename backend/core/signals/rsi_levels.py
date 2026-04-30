"""RSI overbought / oversold bounce detector."""
from __future__ import annotations

from typing import Any

from core.indicators import compute_indicator
from core.signals.types import Signal

OVERSOLD_LEVEL = 30.0
OVERBOUGHT_LEVEL = 70.0


def detect_rsi_signals(
    bars: list[dict[str, Any]], *, period: int = 14,
) -> list[Signal]:
    """Emit a buy when RSI crosses back above 30 (oversold bounce) and a sell
    when it crosses back below 70 (overbought fade).
    """
    if len(bars) < period + 1:
        return []
    closes = [float(b.get("close") or 0.0) for b in bars]
    series = compute_indicator("rsi", closes, params={"period": period})
    rsi = series.get("value") or []
    if not rsi:
        return []

    out: list[Signal] = []
    deepest_oversold: float | None = None
    deepest_overbought: float | None = None

    for i in range(1, len(bars)):
        if i >= len(rsi):
            break
        prev, curr = rsi[i - 1], rsi[i]
        if prev is None or curr is None:
            continue

        if curr < OVERSOLD_LEVEL:
            deepest_oversold = curr if deepest_oversold is None else min(deepest_oversold, curr)
        if curr > OVERBOUGHT_LEVEL:
            deepest_overbought = curr if deepest_overbought is None else max(deepest_overbought, curr)

        if prev < OVERSOLD_LEVEL <= curr:
            base = deepest_oversold if deepest_oversold is not None else prev
            depth = OVERSOLD_LEVEL - base
            strength = max(0.0, min(1.0, depth / 30.0))
            out.append(Signal(
                kind="rsi_oversold_bounce", direction="buy", strength=strength,
                ts=bars[i].get("timestamp"), bar_index=i,
                interpretation=f"RSI bounced from {base:.1f} back above 30 (now {curr:.1f})",
            ))
            deepest_oversold = None
        elif prev > OVERBOUGHT_LEVEL >= curr:
            base = deepest_overbought if deepest_overbought is not None else prev
            height = base - OVERBOUGHT_LEVEL
            strength = max(0.0, min(1.0, height / 30.0))
            out.append(Signal(
                kind="rsi_overbought_fade", direction="sell", strength=strength,
                ts=bars[i].get("timestamp"), bar_index=i,
                interpretation=f"RSI faded from {base:.1f} back below 70 (now {curr:.1f})",
            ))
            deepest_overbought = None
    return out
