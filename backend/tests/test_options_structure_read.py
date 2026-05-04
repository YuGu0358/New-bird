"""Unit tests for the structural-pattern recognition module.

Pure compute — tests build the named inputs by hand and assert the
classifier picks the correct pattern + player + signals_fired set, plus
guarantees around graceful None-handling and rationale ordering.
"""
from __future__ import annotations

from core.options_chain import StructureRead, read_structure
from core.options_chain.structure_read import (
    PATTERN_FREE_RANGE,
    PATTERN_PIN_COMPRESSION,
    PATTERN_SLOW_DEATH_CALLS,
    PATTERN_SLOW_DEATH_PUTS,
    PATTERN_UNCLEAR,
    PLAYER_CALL_SELLER,
    PLAYER_DIRECTIONAL_BUYER,
    PLAYER_IRON_CONDOR_SELLER,
    PLAYER_NO_EDGE,
    PLAYER_PUT_SELLER,
    SIGNAL_CALL_SKEW,
    SIGNAL_HIGH_PINNING,
    SIGNAL_IV_COMPRESSED,
    SIGNAL_PUT_SKEW,
    SIGNAL_WALLS_CLUSTERED,
)


def test_pin_compression_fires_when_iv_low_walls_tight_pinning_high_no_skew():
    """All three core signals (no skew) → PIN_COMPRESSION → iron-condor seller."""
    result = read_structure(
        spot=100.0,
        call_wall=102.0,
        put_wall=98.0,
        max_pain=100.0,
        atm_iv=0.18,
        expected_move_pct=0.015,
        iv_rank=0.10,
        put_call_oi_ratio=1.0,  # neutral — no skew
        pinning_score=80,
    )
    assert isinstance(result, StructureRead)
    assert result.pattern == PATTERN_PIN_COMPRESSION
    assert result.winning_player == PLAYER_IRON_CONDOR_SELLER
    assert SIGNAL_IV_COMPRESSED in result.signals_fired
    assert SIGNAL_WALLS_CLUSTERED in result.signals_fired
    assert SIGNAL_HIGH_PINNING in result.signals_fired
    assert SIGNAL_CALL_SKEW not in result.signals_fired
    assert SIGNAL_PUT_SKEW not in result.signals_fired


def test_slow_death_calls_fires_when_call_skew_and_call_wall_within_5pct_above_spot():
    """call_skew AND call_wall within +5% of spot → SLOW_DEATH_CALLS."""
    result = read_structure(
        spot=100.0,
        call_wall=103.0,  # +3% above spot, within band
        put_wall=80.0,  # far away, walls not clustered
        max_pain=102.0,
        atm_iv=0.30,
        expected_move_pct=0.04,
        iv_rank=0.50,  # not compressed
        put_call_oi_ratio=0.4,  # < 0.6 → call_skew
        pinning_score=20,
    )
    assert result.pattern == PATTERN_SLOW_DEATH_CALLS
    assert result.winning_player == PLAYER_CALL_SELLER
    assert SIGNAL_CALL_SKEW in result.signals_fired
    assert SIGNAL_PUT_SKEW not in result.signals_fired


def test_slow_death_puts_fires_when_put_skew_and_put_wall_within_5pct_below_spot():
    """put_skew AND put_wall within −5% of spot → SLOW_DEATH_PUTS."""
    result = read_structure(
        spot=100.0,
        call_wall=130.0,  # very far above, walls not clustered
        put_wall=97.0,  # -3% below spot, within band
        max_pain=98.0,
        atm_iv=0.35,
        expected_move_pct=0.05,
        iv_rank=0.60,  # not compressed
        put_call_oi_ratio=1.8,  # > 1.4 → put_skew
        pinning_score=15,
    )
    assert result.pattern == PATTERN_SLOW_DEATH_PUTS
    assert result.winning_player == PLAYER_PUT_SELLER
    assert SIGNAL_PUT_SKEW in result.signals_fired
    assert SIGNAL_CALL_SKEW not in result.signals_fired


def test_free_range_fires_when_iv_high_and_walls_wide():
    """Not iv_compressed AND not walls_clustered → FREE_RANGE."""
    result = read_structure(
        spot=100.0,
        call_wall=130.0,
        put_wall=70.0,  # 60% wall width
        max_pain=100.0,
        atm_iv=0.45,
        expected_move_pct=0.06,
        iv_rank=0.85,  # high
        put_call_oi_ratio=1.0,  # neutral
        pinning_score=10,
    )
    assert result.pattern == PATTERN_FREE_RANGE
    assert result.winning_player == PLAYER_DIRECTIONAL_BUYER
    assert SIGNAL_IV_COMPRESSED not in result.signals_fired
    assert SIGNAL_WALLS_CLUSTERED not in result.signals_fired


def test_unclear_fallback_when_nothing_decisive():
    """IV compressed but walls wide and no pinning/skew → UNCLEAR."""
    result = read_structure(
        spot=100.0,
        call_wall=130.0,
        put_wall=70.0,  # wall width 60% → not clustered
        max_pain=100.0,
        atm_iv=0.18,
        expected_move_pct=0.04,
        iv_rank=0.20,  # compressed → blocks FREE_RANGE
        put_call_oi_ratio=1.0,  # no skew → blocks SLOW_DEATH_*
        pinning_score=10,  # blocks PIN_COMPRESSION (no high_pinning)
    )
    assert result.pattern == PATTERN_UNCLEAR
    assert result.winning_player == PLAYER_NO_EDGE


def test_pattern_priority_pin_compression_beats_free_range_at_borderline():
    """Iteration order: PIN_COMPRESSION runs before FREE_RANGE.

    With iv_rank just under the compressed threshold and walls clustered,
    iv_compressed=True so FREE_RANGE cannot fire even if other signals
    suggest range-bound chop. This guards the decision-tree order.
    """
    # iv_rank just below threshold (compressed=True) → FREE_RANGE blocked.
    # walls clustered, pinning high, no skew → PIN_COMPRESSION fires.
    result_pin = read_structure(
        spot=100.0,
        call_wall=102.0,
        put_wall=98.0,
        max_pain=100.0,
        atm_iv=0.18,
        expected_move_pct=0.015,
        iv_rank=0.29,  # < 0.30 boundary
        put_call_oi_ratio=1.0,
        pinning_score=70,
    )
    assert result_pin.pattern == PATTERN_PIN_COMPRESSION

    # And nudge iv_rank just above boundary: PIN_COMPRESSION blocked,
    # walls still clustered (so FREE_RANGE blocked too) → UNCLEAR.
    result_borderline = read_structure(
        spot=100.0,
        call_wall=102.0,
        put_wall=98.0,
        max_pain=100.0,
        atm_iv=0.18,
        expected_move_pct=0.015,
        iv_rank=0.31,  # > 0.30 — not compressed
        put_call_oi_ratio=1.0,
        pinning_score=70,
    )
    assert result_borderline.pattern == PATTERN_UNCLEAR


def test_skew_exclusivity_call_and_put_cannot_both_appear():
    """A single put/call ratio cannot be both < 0.6 AND > 1.4."""
    # Sweep representative ratios — skew flags must always be mutually exclusive.
    for ratio in [0.3, 0.5, 0.59, 0.6, 1.0, 1.4, 1.41, 2.0, 5.0]:
        result = read_structure(
            spot=100.0,
            call_wall=110.0,
            put_wall=90.0,
            max_pain=100.0,
            atm_iv=0.30,
            expected_move_pct=0.03,
            iv_rank=0.50,
            put_call_oi_ratio=ratio,
            pinning_score=20,
        )
        assert not (
            SIGNAL_CALL_SKEW in result.signals_fired
            and SIGNAL_PUT_SKEW in result.signals_fired
        ), f"ratio={ratio} produced both skew signals"


def test_missing_inputs_degrade_gracefully_without_crash():
    """Every signal must tolerate None inputs without raising."""
    result = read_structure(
        spot=100.0,
        call_wall=None,
        put_wall=None,
        max_pain=None,
        atm_iv=None,
        expected_move_pct=None,
        iv_rank=None,
        put_call_oi_ratio=None,
        pinning_score=None,
    )
    assert isinstance(result, StructureRead)
    # No signals can fire when every input is None.
    assert result.signals_fired == []
    # Walls absent → not clustered; IV missing → not compressed; thus FREE_RANGE
    # technically matches (NOT iv_compressed AND NOT walls_clustered).
    assert result.pattern == PATTERN_FREE_RANGE
    assert result.confidence == 0
    # Inputs should be echoed transparently for the UI tooltip.
    assert result.inputs_used["spot"] == 100.0
    assert result.inputs_used["call_wall"] is None
    assert result.inputs_used["pinning_score"] is None


def test_confidence_equals_20x_signals_fired():
    """confidence is len(signals_fired) * 20 — never anything else."""
    # 0 signals
    r0 = read_structure(
        spot=100.0,
        call_wall=None,
        put_wall=None,
        max_pain=None,
        atm_iv=None,
        expected_move_pct=None,
        iv_rank=None,
        put_call_oi_ratio=None,
        pinning_score=None,
    )
    assert r0.confidence == 0 == len(r0.signals_fired) * 20

    # 3 signals (PIN_COMPRESSION setup)
    r3 = read_structure(
        spot=100.0,
        call_wall=102.0,
        put_wall=98.0,
        max_pain=100.0,
        atm_iv=0.18,
        expected_move_pct=0.015,
        iv_rank=0.10,
        put_call_oi_ratio=1.0,
        pinning_score=80,
    )
    assert r3.confidence == 60 == len(r3.signals_fired) * 20

    # 4 signals — call_skew + walls_clustered + iv_compressed + high_pinning
    r4 = read_structure(
        spot=100.0,
        call_wall=102.0,
        put_wall=98.0,
        max_pain=100.0,
        atm_iv=0.18,
        expected_move_pct=0.015,
        iv_rank=0.10,
        put_call_oi_ratio=0.4,
        pinning_score=80,
    )
    assert r4.confidence == 80 == len(r4.signals_fired) * 20


def test_rationale_non_empty_for_non_unclear_pattern():
    """Whenever a non-UNCLEAR pattern is chosen, rationale must have entries."""
    # PIN_COMPRESSION
    r_pin = read_structure(
        spot=100.0, call_wall=102.0, put_wall=98.0, max_pain=100.0,
        atm_iv=0.18, expected_move_pct=0.015, iv_rank=0.10,
        put_call_oi_ratio=1.0, pinning_score=80,
    )
    assert r_pin.pattern == PATTERN_PIN_COMPRESSION
    assert len(r_pin.rationale) > 0

    # SLOW_DEATH_CALLS
    r_calls = read_structure(
        spot=100.0, call_wall=103.0, put_wall=80.0, max_pain=102.0,
        atm_iv=0.30, expected_move_pct=0.04, iv_rank=0.50,
        put_call_oi_ratio=0.4, pinning_score=20,
    )
    assert r_calls.pattern == PATTERN_SLOW_DEATH_CALLS
    assert len(r_calls.rationale) > 0

    # SLOW_DEATH_PUTS
    r_puts = read_structure(
        spot=100.0, call_wall=130.0, put_wall=97.0, max_pain=98.0,
        atm_iv=0.35, expected_move_pct=0.05, iv_rank=0.60,
        put_call_oi_ratio=1.8, pinning_score=15,
    )
    assert r_puts.pattern == PATTERN_SLOW_DEATH_PUTS
    assert len(r_puts.rationale) > 0

    # FREE_RANGE
    r_free = read_structure(
        spot=100.0, call_wall=130.0, put_wall=70.0, max_pain=100.0,
        atm_iv=0.45, expected_move_pct=0.06, iv_rank=0.85,
        put_call_oi_ratio=1.0, pinning_score=10,
    )
    assert r_free.pattern == PATTERN_FREE_RANGE
    assert len(r_free.rationale) > 0
