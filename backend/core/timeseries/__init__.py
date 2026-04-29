"""Time-series aggregation helpers — pure compute, no I/O.

Designed for converting irregular timestamped observations (price ticks,
position snapshots, FRED indicator releases, GEX gauges) into regular
OHLC bars plus simple rolling-window stats. Future services that own
time-series tables (Phase 2's position_snapshots, etc.) call into here
instead of reimplementing the same windowing math.
"""
from core.timeseries.aggregation import (
    Bucket,
    BucketSize,
    Observation,
    OhlcBar,
    bucket_observations,
    rolling_window,
    to_ohlc_bars,
)

__all__ = [
    "Bucket",
    "BucketSize",
    "Observation",
    "OhlcBar",
    "bucket_observations",
    "rolling_window",
    "to_ohlc_bars",
]
