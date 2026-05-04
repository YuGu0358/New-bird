"""Threshold engine — turn an indicator value into a signal level.

Same convention as Tradewell: ok / warn / danger / neutral. The frontend
renders these as a colored signal dot next to each indicator card.
"""
from __future__ import annotations

from typing import Any, Literal

SignalLevel = Literal["ok", "warn", "danger", "neutral"]


def evaluate_signal(value: float | None, thresholds: dict[str, Any]) -> SignalLevel:
    """Map a numeric value to a signal level using a threshold spec.

    Threshold spec shape::

        {
          "ok_max":     <float>,    # value <= this is OK
          "warn_max":   <float>,    # value <= this is WARN
          "danger_max": <float>,    # value <= this is DANGER (else still danger)
          "direction":  "higher_is_worse" | "higher_is_better" | "informational"
        }

    Missing fields default to "informational" → neutral.
    """
    if value is None:
        return "neutral"
    direction = thresholds.get("direction", "informational")
    if direction == "informational":
        return "neutral"

    ok_max = thresholds.get("ok_max")
    warn_max = thresholds.get("warn_max")
    danger_max = thresholds.get("danger_max")
    if ok_max is None or warn_max is None or danger_max is None:
        return "neutral"

    if direction == "higher_is_worse":
        if value <= ok_max:
            return "ok"
        if value <= warn_max:
            return "warn"
        return "danger"

    if direction == "higher_is_better":
        if value >= warn_max:
            return "ok"
        if value >= ok_max:
            return "warn"
        return "danger"

    return "neutral"
