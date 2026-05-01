"""RSI bullish/bearish divergence detector.

Bullish: price LL + RSI HL (downtrend exhaustion).
Bearish: price HH + RSI LH (uptrend exhaustion).
"""
from __future__ import annotations

from typing import Iterable, Sequence

from core.indicators import compute_indicator
from core.signals.types import Signal


def _local_extremes(values: Sequence[float], window: int = 5) -> list[tuple[int, float, str]]:
    """Find local lows and highs using a centered window.

    Returns a list of (index, value, kind) tuples where kind is 'low' or 'high'.
    A point at index i is a local low iff values[i] is the minimum within
    [i-window, i+window]. Same for highs.
    """
    extremes: list[tuple[int, float, str]] = []
    for i in range(window, len(values) - window):
        seg = values[i - window: i + window + 1]
        v = values[i]
        if v is None or any(x is None for x in seg):
            continue
        if v == min(seg) and seg.count(v) == 1:
            extremes.append((i, float(v), "low"))
        elif v == max(seg) and seg.count(v) == 1:
            extremes.append((i, float(v), "high"))
    return extremes


def detect_rsi_divergences(
    closes: Iterable[float],
    period: int = 14,
    pivot_window: int = 5,
    min_separation: int = 5,
) -> list[Signal]:
    """Emit a buy on bullish divergence, sell on bearish divergence.

    Compares the most recent two same-kind RSI extremes against the
    corresponding price extremes. ``min_separation`` is the minimum bar
    distance between the two extremes — guards against firing on tiny noise.
    """
    closes_list = [float(x) for x in closes]
    if len(closes_list) < period + 2 * pivot_window + 2:
        return []

    series = compute_indicator("rsi", closes_list, params={"period": period})
    rsi = series.get("value") or []
    if len(rsi) != len(closes_list):
        return []

    rsi_extremes = _local_extremes(rsi, window=pivot_window)
    signals: list[Signal] = []

    last_low_pair = [e for e in rsi_extremes if e[2] == "low"][-2:]
    if len(last_low_pair) == 2:
        (idx_a, rsi_a, _), (idx_b, rsi_b, _) = last_low_pair
        if idx_b - idx_a >= min_separation:
            price_a, price_b = closes_list[idx_a], closes_list[idx_b]
            if price_b < price_a and rsi_b > rsi_a:
                strength = min(1.0, (rsi_b - rsi_a) / 10.0 + abs(price_a - price_b) / max(price_a, 1.0))
                signals.append(Signal(
                    kind="rsi_bullish_divergence",
                    direction="buy",
                    strength=float(round(strength, 3)),
                    ts=None,
                    bar_index=idx_b,
                    interpretation=(
                        f"Price LL ({price_a:.2f}→{price_b:.2f}) but RSI HL "
                        f"({rsi_a:.1f}→{rsi_b:.1f}) — bullish divergence."
                    ),
                ))

    last_high_pair = [e for e in rsi_extremes if e[2] == "high"][-2:]
    if len(last_high_pair) == 2:
        (idx_a, rsi_a, _), (idx_b, rsi_b, _) = last_high_pair
        if idx_b - idx_a >= min_separation:
            price_a, price_b = closes_list[idx_a], closes_list[idx_b]
            if price_b > price_a and rsi_b < rsi_a:
                strength = min(1.0, (rsi_a - rsi_b) / 10.0 + abs(price_b - price_a) / max(price_a, 1.0))
                signals.append(Signal(
                    kind="rsi_bearish_divergence",
                    direction="sell",
                    strength=float(round(strength, 3)),
                    ts=None,
                    bar_index=idx_b,
                    interpretation=(
                        f"Price HH ({price_a:.2f}→{price_b:.2f}) but RSI LH "
                        f"({rsi_a:.1f}→{rsi_b:.1f}) — bearish divergence."
                    ),
                ))

    return signals
