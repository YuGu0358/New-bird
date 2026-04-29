"""Pure-compute time-series helpers.

Three primitives:

1. `bucket_observations` — group an irregular series of (datetime, value)
   tuples into fixed-size time buckets keyed by the bucket's start.
2. `to_ohlc_bars` — turn a bucketed series into OHLC bars (open, high, low,
   close + count + sum) per bucket. Useful for charting position-mark
   evolution from snapshot tables, indicator releases, or GEX history.
3. `rolling_window` — yield (window_start, window_end, [observations])
   triples over a sliding window. Caller computes whatever statistic they
   need on the slice; we don't pre-bake mean/stdev/etc. because some
   callers want robust stats (median, quantiles).

Why no pandas: keeping these primitives stdlib-only means the rest of the
codebase can import them without paying the pandas import cost (~300ms).
yfinance and quantbrain pull pandas separately for their own reasons —
this module deliberately stays out of that dependency tree.

Conventions:
- All datetimes are UTC. Naive datetimes are treated as UTC (same convention
  as the rest of the codebase, e.g. economic_calendar_service).
- Bucket boundaries are aligned to UTC epoch — a 1-hour bucket always
  starts on the hour, not on the first observation. This makes buckets
  comparable across symbols and avoids "bucket drift" when sources
  publish at slightly different cadences.
- Empty input → empty output. No exceptions on degenerate input.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Iterator


@dataclass(frozen=True)
class Observation:
    timestamp: datetime
    value: float


class BucketSize(Enum):
    """Supported bucket sizes — extend as new use cases land.

    Sized in seconds; conversion to timedelta is centralised so callers
    pass a friendly enum rather than an integer.
    """

    MINUTE_1 = 60
    MINUTE_5 = 5 * 60
    MINUTE_15 = 15 * 60
    HOUR_1 = 60 * 60
    HOUR_4 = 4 * 60 * 60
    DAY_1 = 24 * 60 * 60

    @property
    def delta(self) -> timedelta:
        return timedelta(seconds=self.value)


@dataclass
class Bucket:
    start: datetime  # inclusive — UTC, aligned to bucket grid
    observations: list[Observation]


@dataclass
class OhlcBar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    count: int
    sum: float

    @property
    def mean(self) -> float:
        return self.sum / self.count if self.count else 0.0


def _ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _bucket_start(ts: datetime, size: BucketSize) -> datetime:
    """Floor `ts` to the bucket grid anchored at the UTC epoch.

    Using epoch alignment (rather than first-observation alignment) means
    a 5-minute bucket always starts at HH:00 / HH:05 / HH:10 / etc. — UI
    bars line up across symbols even when one source publishes a few
    seconds later than another.
    """
    ts_utc = _ensure_utc(ts)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    seconds = int((ts_utc - epoch).total_seconds())
    floored = seconds - (seconds % size.value)
    return epoch + timedelta(seconds=floored)


def bucket_observations(
    observations: Iterable[Observation],
    *,
    size: BucketSize,
) -> list[Bucket]:
    """Group observations into fixed-size buckets aligned to the UTC epoch.

    Buckets are returned in ascending start-time order. Empty buckets are
    NOT inserted between observations — callers that need a gap-free
    grid should iterate buckets and fill missing windows themselves.
    Observations with the same bucket start collapse into a single
    Bucket whose `observations` list preserves arrival order.
    """
    by_start: dict[datetime, list[Observation]] = {}
    for obs in observations:
        anchor = _bucket_start(obs.timestamp, size)
        by_start.setdefault(anchor, []).append(obs)
    return [
        Bucket(start=start, observations=by_start[start])
        for start in sorted(by_start.keys())
    ]


def to_ohlc_bars(
    observations: Iterable[Observation],
    *,
    size: BucketSize,
) -> list[OhlcBar]:
    """Convert observations to OHLC bars at the requested bucket size.

    Open is the first observation's value within the bucket; close is the
    last; high/low are the max/min. Empty buckets are omitted (same
    convention as `bucket_observations`).
    """
    out: list[OhlcBar] = []
    for bucket in bucket_observations(observations, size=size):
        if not bucket.observations:
            continue
        values = [o.value for o in bucket.observations]
        out.append(
            OhlcBar(
                start=bucket.start,
                open=bucket.observations[0].value,
                high=max(values),
                low=min(values),
                close=bucket.observations[-1].value,
                count=len(values),
                sum=sum(values),
            )
        )
    return out


def rolling_window(
    observations: Iterable[Observation],
    *,
    window: timedelta,
) -> Iterator[tuple[datetime, datetime, list[Observation]]]:
    """Yield (window_start, window_end, [observations_in_window]) triples.

    For each observation in `observations` (in order), the yielded slice
    contains every observation whose timestamp falls in
    `(observation.timestamp - window, observation.timestamp]`. Useful
    for "last N minutes/hours/days of activity at the time of each tick"
    style queries.

    The input must be sorted ascending by timestamp; we don't sort here
    because the typical caller already has a sorted source (DB ORDER BY
    timestamp ASC). If unsorted input matters in a future use case, sort
    upfront — don't add inline sorting here.
    """
    if window <= timedelta(0):
        raise ValueError("window must be positive")
    obs_list = list(observations)
    left = 0
    for right, obs in enumerate(obs_list):
        right_ts = _ensure_utc(obs.timestamp)
        cutoff = right_ts - window
        # Advance left until obs_list[left].timestamp > cutoff.
        while left <= right and _ensure_utc(obs_list[left].timestamp) <= cutoff:
            left += 1
        yield (cutoff, right_ts, obs_list[left : right + 1])
