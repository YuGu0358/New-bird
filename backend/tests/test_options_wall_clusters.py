"""Unit tests for tenor-bucketed wall cluster detection.

Pure-compute coverage: bucketing, threshold cutoff, top-N capping,
distance vs spot, missing-side handling, and cluster ordering.
"""
from __future__ import annotations

from datetime import date, timedelta

from core.options_chain import OptionContract, detect_wall_clusters
from core.options_chain.wall_clusters import (
    BUCKETS,
    CLUSTER_OI_THRESHOLD,
    DEFAULT_TOP_N,
)


TODAY = date(2026, 4, 28)


def _row(*, expiry: date, strike: float, side: str, oi: int) -> OptionContract:
    return OptionContract(
        expiry=expiry,
        strike=strike,
        option_type=side,
        open_interest=oi,
        volume=0,
        iv=0.30,
        delta=0.5 if side == "C" else -0.5,
        gamma=0.01,
    )


def test_buckets_split_by_dte():
    """A contract per bucket should land in exactly the right bucket."""
    rows = [
        _row(expiry=TODAY + timedelta(days=3), strike=100, side="C", oi=1000),  # 0-7
        _row(expiry=TODAY + timedelta(days=20), strike=110, side="C", oi=2000),  # 8-30
        _row(expiry=TODAY + timedelta(days=60), strike=120, side="C", oi=3000),  # 31+
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=105.0, contracts=rows, today=TODAY
    )
    by_label = {b.label: b for b in result.buckets}
    assert by_label["0-7"].contract_count == 1
    assert by_label["8-30"].contract_count == 1
    assert by_label["31+"].contract_count == 1
    assert by_label["0-7"].top_calls[0].strike == 100
    assert by_label["8-30"].top_calls[0].strike == 110
    assert by_label["31+"].top_calls[0].strike == 120


def test_threshold_filters_subpeak_strikes():
    """Strikes below 20% of peak should be excluded."""
    rows = [
        _row(expiry=TODAY + timedelta(days=3), strike=100, side="C", oi=10_000),  # peak
        _row(expiry=TODAY + timedelta(days=3), strike=101, side="C", oi=2_500),  # 25% — keep
        _row(expiry=TODAY + timedelta(days=3), strike=102, side="C", oi=1_500),  # 15% — drop
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=100.0, contracts=rows, today=TODAY, top_n=5
    )
    bucket = next(b for b in result.buckets if b.label == "0-7")
    strikes = [c.strike for c in bucket.top_calls]
    assert 100 in strikes
    assert 101 in strikes
    assert 102 not in strikes


def test_top_n_caps_qualifying_strikes():
    """Even when 5 strikes qualify, default top_n=2 keeps only top 2."""
    rows = [
        _row(expiry=TODAY + timedelta(days=3), strike=100 + i, side="C", oi=10_000 - i * 100)
        for i in range(5)
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=100.0, contracts=rows, today=TODAY
    )
    bucket = next(b for b in result.buckets if b.label == "0-7")
    assert len(bucket.top_calls) == DEFAULT_TOP_N
    # Sorted by OI descending → strikes 100 and 101 win.
    assert bucket.top_calls[0].strike == 100
    assert bucket.top_calls[1].strike == 101
    assert bucket.top_calls[0].oi >= bucket.top_calls[1].oi


def test_calls_and_puts_handled_independently():
    """A bucket should report both call and put clusters separately."""
    rows = [
        _row(expiry=TODAY + timedelta(days=15), strike=110, side="C", oi=5000),
        _row(expiry=TODAY + timedelta(days=15), strike=90, side="P", oi=8000),
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=100.0, contracts=rows, today=TODAY
    )
    bucket = next(b for b in result.buckets if b.label == "8-30")
    assert bucket.peak_call_oi == 5000
    assert bucket.peak_put_oi == 8000
    assert bucket.top_calls[0].strike == 110
    assert bucket.top_puts[0].strike == 90


def test_distance_pct_signed_relative_to_spot():
    """Calls above spot → positive distance; puts below → negative."""
    rows = [
        _row(expiry=TODAY + timedelta(days=15), strike=110, side="C", oi=1000),
        _row(expiry=TODAY + timedelta(days=15), strike=90, side="P", oi=1000),
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=100.0, contracts=rows, today=TODAY
    )
    bucket = next(b for b in result.buckets if b.label == "8-30")
    assert bucket.top_calls[0].distance_pct == 0.10
    assert bucket.top_puts[0].distance_pct == -0.10


def test_distance_pct_none_when_spot_invalid():
    """spot=0 → distance_pct is None (avoid div-by-zero)."""
    rows = [_row(expiry=TODAY + timedelta(days=3), strike=100, side="C", oi=1000)]
    result = detect_wall_clusters(
        ticker="SPY", spot=0.0, contracts=rows, today=TODAY
    )
    bucket = next(b for b in result.buckets if b.label == "0-7")
    assert bucket.top_calls[0].distance_pct is None


def test_aggregates_oi_across_expiries_inside_one_bucket():
    """Two contracts at the same strike, same bucket → summed OI."""
    rows = [
        _row(expiry=TODAY + timedelta(days=10), strike=100, side="C", oi=3000),
        _row(expiry=TODAY + timedelta(days=20), strike=100, side="C", oi=4000),
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=100.0, contracts=rows, today=TODAY
    )
    bucket = next(b for b in result.buckets if b.label == "8-30")
    assert bucket.contract_count == 2
    assert bucket.top_calls[0].strike == 100
    assert bucket.top_calls[0].oi == 7000
    assert bucket.peak_call_oi == 7000


def test_empty_chain_returns_empty_buckets():
    """Empty input → 3 buckets, each with no clusters."""
    result = detect_wall_clusters(
        ticker="SPY", spot=100.0, contracts=[], today=TODAY
    )
    assert len(result.buckets) == len(BUCKETS)
    for b in result.buckets:
        assert b.contract_count == 0
        assert b.top_calls == []
        assert b.top_puts == []
        assert b.peak_call_oi == 0
        assert b.peak_put_oi == 0


def test_bucket_boundary_seven_days_lands_in_first_bucket():
    """DTE=7 → 0-7 bucket; DTE=8 → 8-30 bucket."""
    rows = [
        _row(expiry=TODAY + timedelta(days=7), strike=100, side="C", oi=1000),
        _row(expiry=TODAY + timedelta(days=8), strike=110, side="C", oi=2000),
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=105.0, contracts=rows, today=TODAY
    )
    by_label = {b.label: b for b in result.buckets}
    assert by_label["0-7"].top_calls[0].strike == 100
    assert by_label["8-30"].top_calls[0].strike == 110


def test_bucket_boundary_thirty_days():
    """DTE=30 → 8-30; DTE=31 → 31+."""
    rows = [
        _row(expiry=TODAY + timedelta(days=30), strike=100, side="C", oi=1000),
        _row(expiry=TODAY + timedelta(days=31), strike=110, side="C", oi=2000),
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=105.0, contracts=rows, today=TODAY
    )
    by_label = {b.label: b for b in result.buckets}
    assert by_label["8-30"].top_calls[0].strike == 100
    assert by_label["31+"].top_calls[0].strike == 110


def test_zero_oi_contracts_ignored():
    """Contracts with OI=0 don't shift the peak or appear as clusters."""
    rows = [
        _row(expiry=TODAY + timedelta(days=3), strike=100, side="C", oi=0),
        _row(expiry=TODAY + timedelta(days=3), strike=101, side="C", oi=5000),
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=100.0, contracts=rows, today=TODAY
    )
    bucket = next(b for b in result.buckets if b.label == "0-7")
    assert len(bucket.top_calls) == 1
    assert bucket.top_calls[0].strike == 101


def test_threshold_constants_sanity():
    assert CLUSTER_OI_THRESHOLD == 0.20
    assert DEFAULT_TOP_N == 2


def test_pct_of_peak_is_normalized():
    """The peak strike should report oi_pct_of_peak == 1.0."""
    rows = [
        _row(expiry=TODAY + timedelta(days=15), strike=100, side="C", oi=10_000),
        _row(expiry=TODAY + timedelta(days=15), strike=101, side="C", oi=5_000),
    ]
    result = detect_wall_clusters(
        ticker="SPY", spot=100.0, contracts=rows, today=TODAY
    )
    bucket = next(b for b in result.buckets if b.label == "8-30")
    assert bucket.top_calls[0].oi_pct_of_peak == 1.0
    assert bucket.top_calls[1].oi_pct_of_peak == 0.5
