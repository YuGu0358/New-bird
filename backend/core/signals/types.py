"""Signal value object — what a detector emits."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


SignalKind = Literal[
    "macd_bull_cross", "macd_bear_cross",
    "rsi_oversold_bounce", "rsi_overbought_fade",
    "volume_breakout", "volume_breakdown",
    "price_breakout_high", "price_breakdown_low",
]
SignalDirection = Literal["buy", "sell"]


@dataclass(frozen=True)
class Signal:
    """One detected event on a symbol's chart.

    `strength` is in [0, 1] — detectors score how confident they are.
    `interpretation` is a one-line human-readable summary suitable for
    rendering as a tooltip on a chart marker.
    """

    kind: SignalKind
    direction: SignalDirection
    strength: float
    ts: datetime
    bar_index: int
    interpretation: str
