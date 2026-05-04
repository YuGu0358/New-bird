"""Squeeze Score — compress 4 signals into a 0-100 imminent-move risk score.

Pure compute, no I/O. The service layer feeds in the option chain (already
fetched), an IV-rank value (or None), and short-interest fraction (or None).

Four signals, each worth 25 points:
1. IV rank low      — current IV in the bottom 30% of its 252-day range
2. OI concentration — single strike holds > 5% of total chain OI
3. PC ratio bullish — put_oi / call_oi < 0.5 (call-skewed positioning)
4. Short interest   — short % of float > 15%

If a signal's input is unavailable (e.g., short_interest=None when yfinance
doesn't expose shortPercentOfFloat), that factor is skipped — the max
achievable score drops by 25, which is honest about missing data.

Level cutoffs:
- score < 33 → "low"
- 33 ≤ score < 66 → "med"
- score ≥ 66 → "high"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from core.options_chain.gex import OptionContract


IV_RANK_LOW_THRESHOLD = 0.30
OI_CONCENTRATION_THRESHOLD = 0.05  # one strike > 5% of total chain OI
PUT_CALL_OI_BIAS = 0.50  # put_oi / call_oi < 0.50 = bullish positioning
SHORT_INTEREST_HIGH = 0.15  # > 15% of float

POINTS_PER_SIGNAL = 25
LEVEL_LOW_MAX = 33
LEVEL_MED_MAX = 66


@dataclass
class SqueezeScore:
    score: int
    level: str  # "low" | "med" | "high"
    signals: list[str] = field(default_factory=list)
    factor_scores: dict[str, float] = field(default_factory=dict)
    max_possible: int = 100  # drops by 25 per missing factor


def _level_for(score: int, max_possible: int) -> str:
    """Bucket the (normalized) score into low / med / high.

    Normalize by max_possible so missing factors don't unfairly shrink level.
    """
    if max_possible <= 0:
        return "low"
    pct = (score / max_possible) * 100
    if pct < LEVEL_LOW_MAX:
        return "low"
    if pct < LEVEL_MED_MAX:
        return "med"
    return "high"


def _oi_concentration(contracts: Iterable[OptionContract]) -> float:
    """Highest single-strike OI share of total chain OI (0..1)."""
    by_strike: dict[float, int] = {}
    total = 0
    for c in contracts:
        oi = c.open_interest or 0
        if oi <= 0:
            continue
        by_strike[c.strike] = by_strike.get(c.strike, 0) + oi
        total += oi
    if total <= 0 or not by_strike:
        return 0.0
    return max(by_strike.values()) / total


def compute_put_call_oi_ratio(contracts: Iterable[OptionContract]) -> float | None:
    """put_oi / call_oi. None if either side has zero OI."""
    call_oi = 0
    put_oi = 0
    for c in contracts:
        oi = c.open_interest or 0
        if oi <= 0:
            continue
        if c.option_type.upper() == "C":
            call_oi += oi
        else:
            put_oi += oi
    if call_oi <= 0 or put_oi <= 0:
        return None
    return put_oi / call_oi


def compute_squeeze(
    contracts: list[OptionContract],
    *,
    iv_rank: float | None = None,
    short_interest_frac: float | None = None,
) -> SqueezeScore:
    """Run the 4-factor squeeze model.

    Args:
        contracts: Full option chain (already merged across expiries).
        iv_rank: 0..1 percentile of current IV in its 252-day distribution.
            None means caller couldn't compute it (e.g., no price history);
            that factor is skipped and max_possible drops by 25.
        short_interest_frac: shortPercentOfFloat from yfinance .info, 0..1.
            None means yfinance didn't expose it; factor skipped.

    Returns:
        SqueezeScore with score, level, signals, per-factor breakdown.
    """
    signals: list[str] = []
    factor_scores: dict[str, float] = {}
    score = 0
    max_possible = 0

    # Factor 1: IV rank low
    if iv_rank is not None:
        max_possible += POINTS_PER_SIGNAL
        if iv_rank < IV_RANK_LOW_THRESHOLD:
            score += POINTS_PER_SIGNAL
            signals.append("iv_rank_low")
            factor_scores["iv_rank_low"] = float(POINTS_PER_SIGNAL)
        else:
            factor_scores["iv_rank_low"] = 0.0

    # Factor 2: OI concentration high
    concentration = _oi_concentration(contracts)
    factor_scores["oi_concentration"] = 0.0
    if concentration > 0:
        max_possible += POINTS_PER_SIGNAL
        if concentration > OI_CONCENTRATION_THRESHOLD:
            score += POINTS_PER_SIGNAL
            signals.append("oi_concentration_high")
            factor_scores["oi_concentration"] = float(POINTS_PER_SIGNAL)

    # Factor 3: Put/Call OI ratio call-skewed
    pc_ratio = compute_put_call_oi_ratio(contracts)
    if pc_ratio is not None:
        max_possible += POINTS_PER_SIGNAL
        if pc_ratio < PUT_CALL_OI_BIAS:
            score += POINTS_PER_SIGNAL
            signals.append("put_call_bias_bullish")
            factor_scores["put_call_bias"] = float(POINTS_PER_SIGNAL)
        else:
            factor_scores["put_call_bias"] = 0.0

    # Factor 4: Short interest high
    if short_interest_frac is not None:
        max_possible += POINTS_PER_SIGNAL
        if short_interest_frac > SHORT_INTEREST_HIGH:
            score += POINTS_PER_SIGNAL
            signals.append("short_interest_high")
            factor_scores["short_interest"] = float(POINTS_PER_SIGNAL)
        else:
            factor_scores["short_interest"] = 0.0

    return SqueezeScore(
        score=score,
        level=_level_for(score, max_possible),
        signals=signals,
        factor_scores=factor_scores,
        max_possible=max_possible,
    )
