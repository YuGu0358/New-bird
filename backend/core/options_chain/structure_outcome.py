"""Outcome evaluator for an options-structure thesis.

Pure compute, no I/O. Given a captured snapshot (pattern + walls + spot)
and the underlying's OHLC bars covering [capture_date+1, horizon_end_date],
return whether the pattern's thesis held.

Thesis per pattern:

- ``PIN_COMPRESSION``    spot stays inside [put_wall, call_wall] for the
                         entire horizon — i.e. ``min(low) >= put_wall`` and
                         ``max(high) <= call_wall``. Iron-condor seller wins
                         when nothing escapes the range.
- ``SLOW_DEATH_CALLS``   spot fails to close above ``call_wall`` at the
                         horizon end. We use horizon-end close (not max
                         high) because the call seller only cares whether
                         the wall holds at expiry; intraday wicks above
                         the wall don't break the thesis if it closes back
                         under.
- ``SLOW_DEATH_PUTS``    mirror — horizon-end close >= ``put_wall``.
- ``FREE_RANGE``         |close_h - spot_t| / spot_t > expected_move_pct.
                         Directional buyer wins when the underlying moves
                         more than the implied move.
- ``UNCLEAR``            no thesis to test → status = "no_edge".

Missing inputs (e.g. no walls available) return status="unevaluable".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


PATTERN_PIN_COMPRESSION = "PIN_COMPRESSION"
PATTERN_SLOW_DEATH_CALLS = "SLOW_DEATH_CALLS"
PATTERN_SLOW_DEATH_PUTS = "SLOW_DEATH_PUTS"
PATTERN_FREE_RANGE = "FREE_RANGE"
PATTERN_UNCLEAR = "UNCLEAR"

OUTCOME_HIT = "hit"
OUTCOME_MISS = "miss"
OUTCOME_NO_EDGE = "no_edge"
OUTCOME_UNEVALUABLE = "unevaluable"


@dataclass(frozen=True)
class HorizonBar:
    high: float
    low: float
    close: float


@dataclass
class Outcome:
    status: str  # hit / miss / no_edge / unevaluable
    realized_close: float | None = None
    realized_high: float | None = None
    realized_low: float | None = None
    realized_move_pct: float | None = None
    metric: dict[str, float | bool | None] = field(default_factory=dict)


def _aggregate(bars: Iterable[HorizonBar]) -> tuple[float, float, float] | None:
    """Returns (max_high, min_low, last_close) or None when bars is empty."""
    bars_list = list(bars)
    if not bars_list:
        return None
    max_high = max(b.high for b in bars_list)
    min_low = min(b.low for b in bars_list)
    last_close = bars_list[-1].close
    return max_high, min_low, last_close


def evaluate_outcome(
    *,
    pattern: str,
    spot_at_capture: float,
    call_wall: float | None,
    put_wall: float | None,
    expected_move_pct: float | None,
    bars: list[HorizonBar],
) -> Outcome:
    """Score the captured pattern against the realized OHLC over the horizon."""
    if pattern == PATTERN_UNCLEAR:
        return Outcome(status=OUTCOME_NO_EDGE)

    agg = _aggregate(bars)
    if agg is None or spot_at_capture <= 0:
        return Outcome(status=OUTCOME_UNEVALUABLE)

    max_high, min_low, last_close = agg
    realized_move_pct = (last_close - spot_at_capture) / spot_at_capture

    base = Outcome(
        status=OUTCOME_UNEVALUABLE,
        realized_close=last_close,
        realized_high=max_high,
        realized_low=min_low,
        realized_move_pct=realized_move_pct,
    )

    if pattern == PATTERN_PIN_COMPRESSION:
        if call_wall is None or put_wall is None:
            return base
        in_band = max_high <= call_wall and min_low >= put_wall
        base.status = OUTCOME_HIT if in_band else OUTCOME_MISS
        base.metric = {
            "in_band": in_band,
            "call_breach_pct": (max_high - call_wall) / call_wall if call_wall > 0 else None,
            "put_breach_pct": (put_wall - min_low) / put_wall if put_wall > 0 else None,
        }
        return base

    if pattern == PATTERN_SLOW_DEATH_CALLS:
        if call_wall is None:
            return base
        wall_held = last_close <= call_wall
        base.status = OUTCOME_HIT if wall_held else OUTCOME_MISS
        base.metric = {
            "wall_held": wall_held,
            "close_vs_wall_pct": (last_close - call_wall) / call_wall if call_wall > 0 else None,
        }
        return base

    if pattern == PATTERN_SLOW_DEATH_PUTS:
        if put_wall is None:
            return base
        wall_held = last_close >= put_wall
        base.status = OUTCOME_HIT if wall_held else OUTCOME_MISS
        base.metric = {
            "wall_held": wall_held,
            "close_vs_wall_pct": (last_close - put_wall) / put_wall if put_wall > 0 else None,
        }
        return base

    if pattern == PATTERN_FREE_RANGE:
        if expected_move_pct is None or expected_move_pct <= 0:
            return base
        moved_more = abs(realized_move_pct) > expected_move_pct
        base.status = OUTCOME_HIT if moved_more else OUTCOME_MISS
        base.metric = {
            "moved_more_than_implied": moved_more,
            "implied_move_pct": expected_move_pct,
            "abs_realized_move_pct": abs(realized_move_pct),
        }
        return base

    return base
