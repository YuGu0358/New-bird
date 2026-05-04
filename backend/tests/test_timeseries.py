"""Tests for core.timeseries — pure-compute aggregation helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.timeseries import (
    BucketSize,
    Observation,
    bucket_observations,
    rolling_window,
    to_ohlc_bars,
)


def _obs(year: int, month: int, day: int, hour: int, minute: int, value: float) -> Observation:
    return Observation(
        timestamp=datetime(year, month, day, hour, minute, tzinfo=timezone.utc),
        value=value,
    )


# ---------- bucket_observations ----------


def test_bucket_observations_groups_by_minute():
    obs = [
        _obs(2026, 1, 1, 12, 0, 100.0),
        _obs(2026, 1, 1, 12, 0, 101.0),
        _obs(2026, 1, 1, 12, 5, 105.0),
        _obs(2026, 1, 1, 12, 7, 107.0),
    ]
    buckets = bucket_observations(obs, size=BucketSize.MINUTE_5)
    assert len(buckets) == 2
    assert buckets[0].start == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert len(buckets[0].observations) == 2
    assert buckets[1].start == datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)
    assert len(buckets[1].observations) == 2


def test_bucket_observations_aligned_to_epoch_grid():
    """A 1-hour bucket always starts on the hour, never on the first obs."""
    obs = [_obs(2026, 1, 1, 12, 37, 100.0)]
    buckets = bucket_observations(obs, size=BucketSize.HOUR_1)
    assert buckets[0].start == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_bucket_observations_returns_empty_for_empty_input():
    assert bucket_observations([], size=BucketSize.HOUR_1) == []


def test_bucket_observations_treats_naive_datetime_as_utc():
    naive = Observation(
        timestamp=datetime(2026, 1, 1, 12, 0),  # no tzinfo
        value=42.0,
    )
    buckets = bucket_observations([naive], size=BucketSize.HOUR_1)
    assert len(buckets) == 1
    assert buckets[0].start.tzinfo == timezone.utc


def test_bucket_observations_preserves_arrival_order_within_bucket():
    obs = [
        _obs(2026, 1, 1, 12, 0, 1.0),
        _obs(2026, 1, 1, 12, 1, 2.0),
        _obs(2026, 1, 1, 12, 2, 3.0),
    ]
    buckets = bucket_observations(obs, size=BucketSize.HOUR_1)
    assert [o.value for o in buckets[0].observations] == [1.0, 2.0, 3.0]


# ---------- to_ohlc_bars ----------


def test_ohlc_bar_basic_arithmetic():
    obs = [
        _obs(2026, 1, 1, 12, 0, 100.0),
        _obs(2026, 1, 1, 12, 1, 105.0),
        _obs(2026, 1, 1, 12, 2, 95.0),
        _obs(2026, 1, 1, 12, 3, 102.0),
    ]
    bars = to_ohlc_bars(obs, size=BucketSize.HOUR_1)
    assert len(bars) == 1
    bar = bars[0]
    assert bar.open == 100.0
    assert bar.high == 105.0
    assert bar.low == 95.0
    assert bar.close == 102.0
    assert bar.count == 4
    assert bar.sum == 402.0
    assert bar.mean == pytest.approx(100.5)


def test_ohlc_bar_single_observation_collapses_to_doji():
    obs = [_obs(2026, 1, 1, 12, 0, 100.0)]
    bars = to_ohlc_bars(obs, size=BucketSize.HOUR_1)
    assert len(bars) == 1
    bar = bars[0]
    assert bar.open == bar.high == bar.low == bar.close == 100.0
    assert bar.count == 1


def test_ohlc_bar_multiple_buckets_sorted_ascending():
    obs = [
        _obs(2026, 1, 1, 14, 0, 200.0),  # later bucket first
        _obs(2026, 1, 1, 12, 0, 100.0),
        _obs(2026, 1, 1, 13, 0, 150.0),
    ]
    bars = to_ohlc_bars(obs, size=BucketSize.HOUR_1)
    assert [b.start.hour for b in bars] == [12, 13, 14]


def test_ohlc_bar_omits_empty_buckets():
    """Gaps in the observation timeline produce no bar — caller fills if needed."""
    obs = [
        _obs(2026, 1, 1, 12, 0, 100.0),
        # 13:00 and 14:00 missing
        _obs(2026, 1, 1, 15, 0, 200.0),
    ]
    bars = to_ohlc_bars(obs, size=BucketSize.HOUR_1)
    assert len(bars) == 2  # not 4 — gaps are not synthesized
    assert {b.start.hour for b in bars} == {12, 15}


# ---------- rolling_window ----------


def test_rolling_window_yields_per_observation_slice():
    obs = [
        _obs(2026, 1, 1, 12, 0, 1.0),
        _obs(2026, 1, 1, 12, 1, 2.0),
        _obs(2026, 1, 1, 12, 2, 3.0),
        _obs(2026, 1, 1, 12, 5, 4.0),
    ]
    triples = list(rolling_window(obs, window=timedelta(minutes=2)))
    assert len(triples) == 4
    # Last yields: cutoff = 12:03, so only the 12:02 + 12:05 fall in the
    # half-open (12:03, 12:05] window… no, we're inclusive on the right
    # end (anchored on the obs itself). Let's verify carefully:
    # for obs at 12:05, window=2min → cutoff = 12:03; we keep obs.timestamp > 12:03
    # → only the 12:05 observation.
    cutoff, end, slice_ = triples[-1]
    assert end == datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)
    assert [o.value for o in slice_] == [4.0]


def test_rolling_window_keeps_all_obs_within_window():
    obs = [
        _obs(2026, 1, 1, 12, 0, 1.0),
        _obs(2026, 1, 1, 12, 1, 2.0),
        _obs(2026, 1, 1, 12, 2, 3.0),
    ]
    triples = list(rolling_window(obs, window=timedelta(minutes=5)))
    # All three observations in the same 5-minute window → last triple
    # contains all 3.
    _, _, slice_ = triples[-1]
    assert [o.value for o in slice_] == [1.0, 2.0, 3.0]


def test_rolling_window_rejects_zero_or_negative():
    with pytest.raises(ValueError, match="window must be positive"):
        list(rolling_window([], window=timedelta(0)))
    with pytest.raises(ValueError, match="window must be positive"):
        list(rolling_window([], window=timedelta(seconds=-1)))


def test_rolling_window_handles_empty_input():
    assert list(rolling_window([], window=timedelta(minutes=1))) == []


# ---------- BucketSize ----------


def test_bucket_size_delta_matches_seconds():
    assert BucketSize.MINUTE_5.delta == timedelta(minutes=5)
    assert BucketSize.HOUR_1.delta == timedelta(hours=1)
    assert BucketSize.DAY_1.delta == timedelta(days=1)
