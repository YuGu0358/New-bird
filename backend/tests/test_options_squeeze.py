"""Unit tests for the squeeze score module.

The compute is pure; tests build hand-crafted OptionContract lists and verify
each factor's contribution and the level cutoffs.
"""
from __future__ import annotations

from datetime import date

import pytest

from core.options_chain import OptionContract, compute_squeeze
from core.options_chain.squeeze import (
    OI_CONCENTRATION_THRESHOLD,
    PUT_CALL_OI_BIAS,
)


def _row(strike: float, side: str, oi: int) -> OptionContract:
    return OptionContract(
        expiry=date(2026, 6, 19),
        strike=strike,
        option_type=side,
        open_interest=oi,
        volume=0,
        iv=0.30,
        delta=0.5,
        gamma=0.01,
    )


def _balanced_chain() -> list[OptionContract]:
    """20 strikes, evenly distributed OI, calls ≈ puts → no signal triggers."""
    rows: list[OptionContract] = []
    strikes = [80 + 5 * i for i in range(20)]
    for s in strikes:
        rows.append(_row(s, "C", 1000))
        rows.append(_row(s, "P", 1000))
    return rows


def test_compute_squeeze_all_signals_high():
    """All 4 factors trigger → 100 / 100 → high."""
    rows: list[OptionContract] = []
    # Concentrated OI on a single call strike
    rows.append(_row(100, "C", 50_000))
    # Spread some additional small calls so total call_oi >> put_oi
    for s in (90, 95, 105, 110):
        rows.append(_row(s, "C", 1000))
    # A few small puts so put/call ratio < 0.5
    rows.append(_row(95, "P", 2000))

    score = compute_squeeze(rows, iv_rank=0.10, short_interest_frac=0.25)

    assert score.score == 100
    assert score.max_possible == 100
    assert score.level == "high"
    assert "iv_rank_low" in score.signals
    assert "oi_concentration_high" in score.signals
    assert "put_call_bias_bullish" in score.signals
    assert "short_interest_high" in score.signals


def test_compute_squeeze_no_signals():
    """All factors at neutral → 0 / 100 → low."""
    score = compute_squeeze(
        _balanced_chain(),
        iv_rank=0.80,  # high
        short_interest_frac=0.05,  # low
    )
    assert score.score == 0
    assert score.max_possible == 100
    assert score.level == "low"
    assert score.signals == []


def test_compute_squeeze_partial_two_of_four():
    """Two factors trigger → 50 / 100 → med.

    Construction targets:
    - Concentration high (single strike >> rest): YES
    - Short interest high: YES
    - IV rank low: NO (pass 0.80)
    - PC bias bullish: NO (puts >= calls so ratio >= 0.5)
    """
    # Balance call/put OI so PC ratio = 1.0 (no bias trigger), but pile both
    # legs onto strike 100 so the concentration signal still fires.
    rows: list[OptionContract] = [
        _row(100, "C", 50_000),
        _row(100, "P", 50_000),
    ]
    for s in (90, 95, 105, 110):
        rows.append(_row(s, "C", 5000))
        rows.append(_row(s, "P", 5000))

    score = compute_squeeze(rows, iv_rank=0.80, short_interest_frac=0.25)
    assert score.score == 50
    assert score.level == "med"
    assert "oi_concentration_high" in score.signals
    assert "short_interest_high" in score.signals
    assert "put_call_bias_bullish" not in score.signals
    assert "iv_rank_low" not in score.signals


def test_compute_squeeze_handles_missing_short_interest():
    """short_interest=None → factor skipped, max drops to 75."""
    score = compute_squeeze(
        _balanced_chain(),
        iv_rank=0.80,
        short_interest_frac=None,
    )
    assert score.max_possible == 75
    assert "short_interest_high" not in score.signals
    assert "short_interest" not in score.factor_scores


def test_compute_squeeze_handles_missing_iv_rank():
    """iv_rank=None → factor skipped, max drops to 75."""
    score = compute_squeeze(
        _balanced_chain(),
        iv_rank=None,
        short_interest_frac=0.05,
    )
    assert score.max_possible == 75
    assert "iv_rank_low" not in score.signals
    assert "iv_rank_low" not in score.factor_scores


def test_compute_squeeze_empty_chain_no_oi_signals():
    """Empty chain → concentration / pc_ratio factors absent."""
    score = compute_squeeze([], iv_rank=0.10, short_interest_frac=0.25)
    # Only iv_rank + short_interest contribute (no OI signals available)
    assert score.max_possible == 50
    assert score.score == 50
    assert "oi_concentration_high" not in score.signals
    assert "put_call_bias_bullish" not in score.signals


def test_level_normalized_for_missing_factors():
    """A perfect score over 50 max_possible should still be 'high'."""
    score = compute_squeeze([], iv_rank=0.10, short_interest_frac=0.25)
    assert score.score == 50
    assert score.max_possible == 50
    # 50/50 = 100% → high
    assert score.level == "high"


def test_oi_concentration_threshold_boundary():
    """Concentration exactly at threshold should NOT trigger (uses strict >)."""
    # 5 strikes, equal OI → max share = 20% > 5% → triggers
    rows = [_row(100 + i, "C", 1000) for i in range(5)]
    score = compute_squeeze(rows, iv_rank=0.80, short_interest_frac=0.05)
    assert "oi_concentration_high" in score.signals
    # Now spread very evenly across 25 strikes → 4% each → no trigger
    rows_spread = [_row(100 + i, "C", 1000) for i in range(25)]
    score2 = compute_squeeze(rows_spread, iv_rank=0.80, short_interest_frac=0.05)
    assert "oi_concentration_high" not in score2.signals


def test_put_call_bias_threshold():
    """put_oi/call_oi at boundary 0.5 should NOT trigger (uses strict <)."""
    rows: list[OptionContract] = [
        _row(100, "C", 2000),
        _row(100, "P", 1000),
    ]
    # ratio = 0.5 exactly → no trigger
    score = compute_squeeze(rows, iv_rank=0.80, short_interest_frac=0.05)
    assert "put_call_bias_bullish" not in score.signals
    # ratio = 0.4 → trigger
    rows2: list[OptionContract] = [
        _row(100, "C", 2500),
        _row(100, "P", 1000),
    ]
    score2 = compute_squeeze(rows2, iv_rank=0.80, short_interest_frac=0.05)
    assert "put_call_bias_bullish" in score2.signals


def test_thresholds_sanity():
    """Sanity check on constants (regression guard)."""
    assert OI_CONCENTRATION_THRESHOLD == 0.05
    assert PUT_CALL_OI_BIAS == 0.50


@pytest.mark.parametrize(
    "iv,si,expected_signals",
    [
        (0.20, 0.20, {"iv_rank_low", "short_interest_high"}),
        (0.50, 0.20, {"short_interest_high"}),
        (0.20, 0.05, {"iv_rank_low"}),
        (0.50, 0.05, set()),
    ],
)
def test_compute_squeeze_factor_combinations(iv, si, expected_signals):
    score = compute_squeeze(_balanced_chain(), iv_rank=iv, short_interest_frac=si)
    assert set(score.signals) == expected_signals
