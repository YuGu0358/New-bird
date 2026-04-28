"""Unit tests for the OI-to-float analysis module.

Pure compute; tests build hand-crafted OptionContract lists and verify the
exact arithmetic of notional + delta-adjusted shares against the public float.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

from core.options_chain import OptionContract, compute_oi_float
from core.options_chain.oi_float import CONTRACT_MULTIPLIER


def _row(
    strike: float,
    side: str,
    oi: int,
    delta: float | None = 0.5,
) -> OptionContract:
    return OptionContract(
        expiry=date(2026, 6, 19),
        strike=strike,
        option_type=side,
        open_interest=oi,
        volume=0,
        iv=0.30,
        delta=delta,
        gamma=0.01,
    )


def test_all_call_chain_exact_arithmetic():
    """3 strikes x 1000 OI x delta 0.5 → notional 300k, delta-adj 150k."""
    rows = [
        _row(100, "C", 1000, delta=0.5),
        _row(105, "C", 1000, delta=0.5),
        _row(110, "C", 1000, delta=0.5),
    ]
    out = compute_oi_float(rows, float_shares=1_000_000)

    assert out.total_call_oi == 3000
    assert out.total_put_oi == 0
    assert out.notional_call_shares == 3000 * CONTRACT_MULTIPLIER == 300_000
    assert out.notional_put_shares == 0
    assert out.notional_total_shares == 300_000
    assert out.delta_adjusted_call_shares == 3000 * 0.5 * CONTRACT_MULTIPLIER == 150_000
    assert out.delta_adjusted_put_shares == 0.0
    assert out.delta_adjusted_total_shares == 150_000

    assert out.notional_call_pct == 0.30
    assert out.notional_put_pct == 0.0
    assert out.notional_total_pct == 0.30
    assert out.delta_adjusted_call_pct == 0.15
    assert out.delta_adjusted_put_pct == 0.0
    assert out.delta_adjusted_total_pct == 0.15

    assert out.contracts_with_delta == 3
    assert out.contracts_total == 3


def test_mixed_call_put_totals_are_sums():
    """Calls and puts computed independently; totals are simple sums."""
    rows = [
        _row(100, "C", 2000, delta=0.6),
        _row(105, "C", 1000, delta=0.4),
        _row(95, "P", 1500, delta=-0.3),
        _row(90, "P", 500, delta=-0.2),
    ]
    out = compute_oi_float(rows, float_shares=10_000_000)

    expected_notional_call = (2000 + 1000) * CONTRACT_MULTIPLIER
    expected_notional_put = (1500 + 500) * CONTRACT_MULTIPLIER
    expected_delta_call = (2000 * 0.6 + 1000 * 0.4) * CONTRACT_MULTIPLIER
    expected_delta_put = (1500 * 0.3 + 500 * 0.2) * CONTRACT_MULTIPLIER

    assert out.total_call_oi == 3000
    assert out.total_put_oi == 2000
    assert out.notional_call_shares == expected_notional_call
    assert out.notional_put_shares == expected_notional_put
    assert out.notional_total_shares == expected_notional_call + expected_notional_put
    assert out.delta_adjusted_call_shares == expected_delta_call
    assert out.delta_adjusted_put_shares == expected_delta_put
    assert (
        out.delta_adjusted_total_shares
        == expected_delta_call + expected_delta_put
    )
    # Totals match sum of halves at the pct level too.
    assert out.notional_total_pct is not None
    assert out.notional_call_pct is not None
    assert out.notional_put_pct is not None
    assert abs(
        out.notional_total_pct - (out.notional_call_pct + out.notional_put_pct)
    ) < 1e-12


def test_negative_put_delta_uses_absolute_value():
    """A put with delta -0.6 contributes 0.6 * oi * 100 to delta_adjusted."""
    rows = [_row(100, "P", 1000, delta=-0.6)]
    out = compute_oi_float(rows, float_shares=1_000_000)

    assert out.delta_adjusted_put_shares == 0.6 * 1000 * CONTRACT_MULTIPLIER
    assert out.delta_adjusted_put_shares == 60_000
    assert out.delta_adjusted_call_shares == 0.0
    assert out.delta_adjusted_put_pct == 0.06


def test_missing_delta_skipped_but_counted_in_total():
    """delta=None → excluded from delta sum, still counted in contracts_total."""
    rows = [
        _row(100, "C", 1000, delta=0.5),
        _row(105, "C", 1000, delta=None),
        _row(95, "P", 1000, delta=-0.4),
        _row(90, "P", 1000, delta=None),
    ]
    out = compute_oi_float(rows, float_shares=1_000_000)

    # Notional unaffected by missing delta.
    assert out.notional_call_shares == 2000 * CONTRACT_MULTIPLIER
    assert out.notional_put_shares == 2000 * CONTRACT_MULTIPLIER
    # Delta-adjusted only includes rows that had delta.
    assert out.delta_adjusted_call_shares == 0.5 * 1000 * CONTRACT_MULTIPLIER
    assert out.delta_adjusted_put_shares == 0.4 * 1000 * CONTRACT_MULTIPLIER
    # Diagnostics
    assert out.contracts_with_delta == 2
    assert out.contracts_total == 4
    assert out.contracts_with_delta < out.contracts_total


def test_zero_oi_rows_skipped_completely():
    """oi <= 0 → no contribution to notional, delta-adj, or contracts_with_delta.

    The row should still bump `contracts_total` (the spec separates
    "contracts seen" from "contracts that contributed").
    """
    rows = [
        _row(100, "C", 1000, delta=0.5),
        _row(105, "C", 0, delta=0.5),  # zero OI
        _row(110, "C", 0, delta=None),  # zero OI + missing delta
    ]
    out = compute_oi_float(rows, float_shares=1_000_000)

    assert out.total_call_oi == 1000
    assert out.notional_call_shares == 1000 * CONTRACT_MULTIPLIER
    assert out.delta_adjusted_call_shares == 0.5 * 1000 * CONTRACT_MULTIPLIER
    # Only the OI > 0 row that had delta contributes.
    assert out.contracts_with_delta == 1
    # All rows seen.
    assert out.contracts_total == 3


def test_float_shares_none_yields_none_pcts_but_shares_still_computed():
    rows = [
        _row(100, "C", 1000, delta=0.5),
        _row(95, "P", 1000, delta=-0.5),
    ]
    out = compute_oi_float(rows, float_shares=None)

    assert out.notional_call_shares == 1000 * CONTRACT_MULTIPLIER
    assert out.notional_put_shares == 1000 * CONTRACT_MULTIPLIER
    assert out.delta_adjusted_call_shares == 0.5 * 1000 * CONTRACT_MULTIPLIER
    assert out.delta_adjusted_put_shares == 0.5 * 1000 * CONTRACT_MULTIPLIER

    assert out.notional_call_pct is None
    assert out.notional_put_pct is None
    assert out.notional_total_pct is None
    assert out.delta_adjusted_call_pct is None
    assert out.delta_adjusted_put_pct is None
    assert out.delta_adjusted_total_pct is None


def test_float_shares_non_positive_treated_as_missing():
    """0 / negative float → all pcts None (defensive against bad data)."""
    rows = [_row(100, "C", 1000, delta=0.5)]

    for bad in (0, -1, -1_000_000):
        out = compute_oi_float(rows, float_shares=bad)
        assert out.notional_call_pct is None
        assert out.notional_put_pct is None
        assert out.notional_total_pct is None
        assert out.delta_adjusted_call_pct is None
        assert out.delta_adjusted_put_pct is None
        assert out.delta_adjusted_total_pct is None
        # Shares still compute.
        assert out.notional_call_shares == 1000 * CONTRACT_MULTIPLIER


def test_empty_chain():
    """No contracts → all-zero shares, contract counts zero, pcts as expected."""
    out_with_float = compute_oi_float([], float_shares=1_000_000)
    assert out_with_float.total_call_oi == 0
    assert out_with_float.total_put_oi == 0
    assert out_with_float.notional_call_shares == 0
    assert out_with_float.notional_put_shares == 0
    assert out_with_float.notional_total_shares == 0
    assert out_with_float.delta_adjusted_call_shares == 0.0
    assert out_with_float.delta_adjusted_put_shares == 0.0
    assert out_with_float.delta_adjusted_total_shares == 0.0
    # With float supplied, shares=0 → pct=0 (not None).
    assert out_with_float.notional_call_pct == 0.0
    assert out_with_float.notional_put_pct == 0.0
    assert out_with_float.notional_total_pct == 0.0
    assert out_with_float.delta_adjusted_call_pct == 0.0
    assert out_with_float.delta_adjusted_put_pct == 0.0
    assert out_with_float.delta_adjusted_total_pct == 0.0
    assert out_with_float.contracts_with_delta == 0
    assert out_with_float.contracts_total == 0

    out_no_float = compute_oi_float([], float_shares=None)
    assert out_no_float.notional_total_pct is None
    assert out_no_float.delta_adjusted_total_pct is None
    assert out_no_float.contracts_total == 0


def test_delta_adjusted_le_notional_invariant():
    """|delta| <= 1 → delta-adjusted shares <= notional shares at every level."""
    rows = [
        _row(100, "C", 5000, delta=0.95),
        _row(110, "C", 3000, delta=0.55),
        _row(120, "C", 2000, delta=0.10),
        _row(95, "P", 4000, delta=-0.45),
        _row(85, "P", 1000, delta=-0.05),
        _row(80, "P", 500, delta=None),  # excluded from delta sum
    ]
    out = compute_oi_float(rows, float_shares=10_000_000)

    assert out.delta_adjusted_call_shares <= out.notional_call_shares
    assert out.delta_adjusted_put_shares <= out.notional_put_shares
    assert out.delta_adjusted_total_shares <= out.notional_total_shares
    # And at the pct level when float is set.
    assert out.delta_adjusted_total_pct is not None
    assert out.notional_total_pct is not None
    assert out.delta_adjusted_total_pct <= out.notional_total_pct


def test_determinism():
    """Same input → identical breakdown (no hidden state, no ordering tricks)."""
    rows = [
        _row(100, "C", 1234, delta=0.42),
        _row(105, "C", 555, delta=None),
        _row(95, "P", 777, delta=-0.31),
        _row(85, "P", 0, delta=-0.99),  # zero OI skipped
    ]
    a = compute_oi_float(rows, float_shares=2_500_000)
    b = compute_oi_float([replace(r) for r in rows], float_shares=2_500_000)
    assert a == b
