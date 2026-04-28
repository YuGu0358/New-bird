"""Structural Pattern Recognition — classify the option market's regime.

Pure compute, no I/O. The service layer feeds in already-computed market
structure inputs (walls, max pain, ATM IV, expected move, IV rank, put/call
OI ratio, pinning score) and we tag the chain with one of four patterns
(plus an UNCLEAR fallback) and the player profile that pattern favors.

Five named signals (booleans):
1. iv_compressed   — IV rank < 0.30 (or ATM IV < 0.20 if rank missing)
2. walls_clustered — |call_wall - put_wall| / spot < max(0.06, 2 × EM%)
3. call_skew       — put_call_oi_ratio < 0.6  (call-heavy positioning)
4. put_skew        — put_call_oi_ratio > 1.4  (put-heavy positioning)
5. high_pinning    — pinning_score >= 60

`call_skew` and `put_skew` are mutually exclusive by construction.

Four named patterns (priority order — first match wins):
- PIN_COMPRESSION   iv_compressed AND walls_clustered AND high_pinning AND
                    no skew. Spot trapped between tight walls, IV crushed,
                    pinning probable. Iron-condor seller wins.
- SLOW_DEATH_CALLS  call_skew AND call_wall within +5% above spot. Bull
                    drift expected to stall at the wall; long calls bleed
                    theta. Call seller wins (long puts work with patience).
- SLOW_DEATH_PUTS   put_skew AND put_wall within −5% below spot. Mirror;
                    put seller wins (long calls work with patience).
- FREE_RANGE        NOT iv_compressed AND NOT walls_clustered. Walls sparse,
                    IV not crushed → directional moves can run. Directional
                    buyer wins.
- UNCLEAR           Fallback when nothing matches. No edge.

Confidence is `len(signals_fired) * 20` (0..100, UI renders as percent).
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Pattern labels
PATTERN_PIN_COMPRESSION = "PIN_COMPRESSION"
PATTERN_SLOW_DEATH_CALLS = "SLOW_DEATH_CALLS"
PATTERN_SLOW_DEATH_PUTS = "SLOW_DEATH_PUTS"
PATTERN_FREE_RANGE = "FREE_RANGE"
PATTERN_UNCLEAR = "UNCLEAR"

# Player labels
PLAYER_IRON_CONDOR_SELLER = "IRON_CONDOR_SELLER_WINS"
PLAYER_CALL_SELLER = "CALL_SELLER_WINS"
PLAYER_PUT_SELLER = "PUT_SELLER_WINS"
PLAYER_DIRECTIONAL_BUYER = "DIRECTIONAL_BUYER_WINS"
PLAYER_NO_EDGE = "NO_EDGE"

# Signal names — fixed order so tests can assert deterministically.
SIGNAL_IV_COMPRESSED = "iv_compressed"
SIGNAL_WALLS_CLUSTERED = "walls_clustered"
SIGNAL_CALL_SKEW = "call_skew"
SIGNAL_PUT_SKEW = "put_skew"
SIGNAL_HIGH_PINNING = "high_pinning"

SIGNAL_ORDER = (
    SIGNAL_IV_COMPRESSED,
    SIGNAL_WALLS_CLUSTERED,
    SIGNAL_CALL_SKEW,
    SIGNAL_PUT_SKEW,
    SIGNAL_HIGH_PINNING,
)

# Thresholds (kept as module constants for transparency / regression guards).
IV_RANK_COMPRESSED_THRESHOLD = 0.30
ATM_IV_COMPRESSED_FALLBACK = 0.20
WALLS_CLUSTERED_FLOOR = 0.06  # 6% of spot, used when expected_move_pct missing
CALL_SKEW_MAX = 0.6
PUT_SKEW_MIN = 1.4
HIGH_PINNING_MIN = 60
SLOW_DEATH_WALL_BAND_PCT = 0.05  # wall within ±5% of spot
CONFIDENCE_PER_SIGNAL = 20


_PLAYER_FOR_PATTERN: dict[str, str] = {
    PATTERN_PIN_COMPRESSION: PLAYER_IRON_CONDOR_SELLER,
    PATTERN_SLOW_DEATH_CALLS: PLAYER_CALL_SELLER,
    PATTERN_SLOW_DEATH_PUTS: PLAYER_PUT_SELLER,
    PATTERN_FREE_RANGE: PLAYER_DIRECTIONAL_BUYER,
    PATTERN_UNCLEAR: PLAYER_NO_EDGE,
}


@dataclass
class StructureRead:
    pattern: str  # one of the PATTERN_* labels
    winning_player: str  # one of the PLAYER_* labels
    confidence: int  # 20 * len(signals_fired), 0..100
    signals_fired: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    inputs_used: dict[str, float | int | None] = field(default_factory=dict)


def _check_iv_compressed(
    iv_rank: float | None, atm_iv: float | None
) -> tuple[bool, str | None]:
    """IV rank < 0.30 (preferred) or atm_iv < 0.20 (fallback when rank missing)."""
    if iv_rank is not None:
        if iv_rank < IV_RANK_COMPRESSED_THRESHOLD:
            return True, f"IV rank {iv_rank:.2f} below {IV_RANK_COMPRESSED_THRESHOLD:.2f} (compressed)"
        return False, None
    if atm_iv is not None:
        if atm_iv < ATM_IV_COMPRESSED_FALLBACK:
            return True, f"ATM IV {atm_iv:.2f} below {ATM_IV_COMPRESSED_FALLBACK:.2f} (compressed; iv_rank unavailable)"
        return False, None
    return False, None


def _check_walls_clustered(
    spot: float,
    call_wall: float | None,
    put_wall: float | None,
    expected_move_pct: float | None,
) -> tuple[bool, str | None]:
    """Walls present and tight: |call_wall - put_wall| / spot < max(0.06, 2 × EM%)."""
    if call_wall is None or put_wall is None or spot <= 0:
        return False, None
    width_pct = abs(call_wall - put_wall) / spot
    if expected_move_pct is not None and expected_move_pct > 0:
        threshold = max(WALLS_CLUSTERED_FLOOR, 2.0 * expected_move_pct)
    else:
        threshold = WALLS_CLUSTERED_FLOOR
    if width_pct < threshold:
        return True, (
            f"wall width {width_pct * 100:.2f}% of spot < {threshold * 100:.2f}% "
            f"(call={call_wall}, put={put_wall})"
        )
    return False, None


def _check_call_skew(put_call_oi_ratio: float | None) -> tuple[bool, str | None]:
    if put_call_oi_ratio is None:
        return False, None
    if put_call_oi_ratio < CALL_SKEW_MAX:
        return True, f"put/call OI ratio {put_call_oi_ratio:.2f} < {CALL_SKEW_MAX} (call-heavy)"
    return False, None


def _check_put_skew(put_call_oi_ratio: float | None) -> tuple[bool, str | None]:
    if put_call_oi_ratio is None:
        return False, None
    if put_call_oi_ratio > PUT_SKEW_MIN:
        return True, f"put/call OI ratio {put_call_oi_ratio:.2f} > {PUT_SKEW_MIN} (put-heavy)"
    return False, None


def _check_high_pinning(pinning_score: int | None) -> tuple[bool, str | None]:
    if pinning_score is None:
        return False, None
    if pinning_score >= HIGH_PINNING_MIN:
        return True, f"pinning score {pinning_score} >= {HIGH_PINNING_MIN}"
    return False, None


def _wall_within_band_above(
    spot: float, wall: float | None, band_pct: float
) -> bool:
    """True iff wall sits 0..band_pct above spot."""
    if wall is None or spot <= 0:
        return False
    diff_pct = (wall - spot) / spot
    return 0.0 <= diff_pct <= band_pct


def _wall_within_band_below(
    spot: float, wall: float | None, band_pct: float
) -> bool:
    """True iff wall sits 0..band_pct below spot."""
    if wall is None or spot <= 0:
        return False
    diff_pct = (spot - wall) / spot
    return 0.0 <= diff_pct <= band_pct


def _decide_pattern(
    *,
    iv_compressed: bool,
    walls_clustered: bool,
    call_skew: bool,
    put_skew: bool,
    high_pinning: bool,
    spot: float,
    call_wall: float | None,
    put_wall: float | None,
) -> tuple[str, str]:
    """Apply patterns in spec order — first match wins. Returns (pattern, why)."""
    # 1. PIN_COMPRESSION
    if (
        iv_compressed
        and walls_clustered
        and high_pinning
        and not (call_skew or put_skew)
    ):
        return (
            PATTERN_PIN_COMPRESSION,
            "pattern=PIN_COMPRESSION: IV crushed, walls tight, pinning likely, no skew",
        )
    # 2. SLOW_DEATH_CALLS
    if call_skew and _wall_within_band_above(spot, call_wall, SLOW_DEATH_WALL_BAND_PCT):
        return (
            PATTERN_SLOW_DEATH_CALLS,
            f"pattern=SLOW_DEATH_CALLS: call-heavy positioning and call wall within "
            f"+{SLOW_DEATH_WALL_BAND_PCT * 100:.0f}% of spot",
        )
    # 3. SLOW_DEATH_PUTS
    if put_skew and _wall_within_band_below(spot, put_wall, SLOW_DEATH_WALL_BAND_PCT):
        return (
            PATTERN_SLOW_DEATH_PUTS,
            f"pattern=SLOW_DEATH_PUTS: put-heavy positioning and put wall within "
            f"-{SLOW_DEATH_WALL_BAND_PCT * 100:.0f}% of spot",
        )
    # 4. FREE_RANGE
    if (not iv_compressed) and (not walls_clustered):
        return (
            PATTERN_FREE_RANGE,
            "pattern=FREE_RANGE: IV not compressed and walls sparse",
        )
    # 5. UNCLEAR fallback
    return (
        PATTERN_UNCLEAR,
        "pattern=UNCLEAR: no decisive structural signature matched",
    )


def read_structure(
    *,
    spot: float,
    call_wall: float | None,
    put_wall: float | None,
    max_pain: float | None,
    atm_iv: float | None,
    expected_move_pct: float | None,
    iv_rank: float | None,
    put_call_oi_ratio: float | None,
    pinning_score: int | None,
) -> StructureRead:
    """Classify which structural pattern the chain is in.

    All inputs are tolerant of `None` — missing values simply prevent the
    associated signal(s) from firing, never crash.
    """
    # Evaluate signals in the canonical order so signals_fired is stable.
    iv_compressed, iv_reason = _check_iv_compressed(iv_rank, atm_iv)
    walls_clustered, walls_reason = _check_walls_clustered(
        spot, call_wall, put_wall, expected_move_pct
    )
    call_skew, call_reason = _check_call_skew(put_call_oi_ratio)
    put_skew, put_reason = _check_put_skew(put_call_oi_ratio)
    high_pinning, pinning_reason = _check_high_pinning(pinning_score)

    signals_and_reasons: list[tuple[str, bool, str | None]] = [
        (SIGNAL_IV_COMPRESSED, iv_compressed, iv_reason),
        (SIGNAL_WALLS_CLUSTERED, walls_clustered, walls_reason),
        (SIGNAL_CALL_SKEW, call_skew, call_reason),
        (SIGNAL_PUT_SKEW, put_skew, put_reason),
        (SIGNAL_HIGH_PINNING, high_pinning, pinning_reason),
    ]
    signals_fired = [name for name, fired, _ in signals_and_reasons if fired]
    rationale: list[str] = [
        f"{name}: {reason}"
        for name, fired, reason in signals_and_reasons
        if fired and reason
    ]

    pattern, decision_reason = _decide_pattern(
        iv_compressed=iv_compressed,
        walls_clustered=walls_clustered,
        call_skew=call_skew,
        put_skew=put_skew,
        high_pinning=high_pinning,
        spot=spot,
        call_wall=call_wall,
        put_wall=put_wall,
    )
    rationale.append(decision_reason)

    winning_player = _PLAYER_FOR_PATTERN[pattern]
    confidence = len(signals_fired) * CONFIDENCE_PER_SIGNAL

    inputs_used: dict[str, float | int | None] = {
        "spot": spot,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "max_pain": max_pain,
        "atm_iv": atm_iv,
        "expected_move_pct": expected_move_pct,
        "iv_rank": iv_rank,
        "put_call_oi_ratio": put_call_oi_ratio,
        "pinning_score": pinning_score,
    }

    return StructureRead(
        pattern=pattern,
        winning_player=winning_player,
        confidence=confidence,
        signals_fired=signals_fired,
        rationale=rationale,
        inputs_used=inputs_used,
    )
