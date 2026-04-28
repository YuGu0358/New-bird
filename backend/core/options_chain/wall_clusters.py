"""Wall Cluster Detection — tenor-bucketed OI clusters.

Walls in /api/options-chain/{ticker} aggregate every expiry into a single
strike grid. That hides which expiry actually owns the wall: a 0-DTE call
wall behaves nothing like a 90-DTE call wall (dealer hedging windows differ
by orders of magnitude). This module splits the chain into three tenor
buckets and reports the dominant clusters in each.

Buckets (calendar DTE, computed against an explicit `today`):
- "0-7"   →  0 < dte ≤ 7        (this week)
- "8-30"  →  7 < dte ≤ 30       (one month)
- "31+"   →  30 < dte            (longer-dated)

For each bucket and each side (call/put) we:
1. Sum OI per strike across every contract in the bucket.
2. Find the peak strike (highest OI) — that's the "anchor" for the bucket.
3. Keep the top N strikes whose OI ≥ CLUSTER_OI_THRESHOLD × peak_oi.

The 20% threshold mirrors how Tradewell defines "cluster" (a strike worth
calling out, not a one-off). It is strict-greater-than-or-equal so a
single-strike chain still surfaces its anchor.

Pure compute, no I/O.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from core.options_chain.gex import OptionContract


CLUSTER_OI_THRESHOLD = 0.20  # min share of peak OI to count as a cluster
DEFAULT_TOP_N = 2


@dataclass(frozen=True)
class TenorBucketSpec:
    """Inclusive on lower bound (exclusive at 0), inclusive on upper.

    Using `dte_max=None` means "no upper bound" (the long-dated bucket).
    """

    label: str
    dte_min: int  # exclusive lower bound; bucket matches dte > dte_min
    dte_max: int | None  # inclusive upper bound; None → unbounded


# Order matters: we iterate from front-month outward.
BUCKETS: tuple[TenorBucketSpec, ...] = (
    TenorBucketSpec(label="0-7", dte_min=-1, dte_max=7),
    TenorBucketSpec(label="8-30", dte_min=7, dte_max=30),
    TenorBucketSpec(label="31+", dte_min=30, dte_max=None),
)


@dataclass
class WallClusterStrike:
    strike: float
    oi: int
    oi_pct_of_peak: float  # 0..1
    distance_pct: float | None  # (strike - spot) / spot, None if spot ≤ 0


@dataclass
class WallClusterBucket:
    label: str
    dte_min: int
    dte_max: int | None
    contract_count: int
    peak_call_oi: int
    peak_put_oi: int
    top_calls: list[WallClusterStrike] = field(default_factory=list)
    top_puts: list[WallClusterStrike] = field(default_factory=list)


@dataclass
class WallClusters:
    ticker: str
    spot: float
    threshold_pct: float
    top_n: int
    buckets: list[WallClusterBucket] = field(default_factory=list)


def _bucket_for(dte: int, specs: tuple[TenorBucketSpec, ...]) -> TenorBucketSpec | None:
    for spec in specs:
        if dte > spec.dte_min and (spec.dte_max is None or dte <= spec.dte_max):
            return spec
    return None


def _aggregate_oi_by_strike(
    contracts: Iterable[OptionContract], side: str
) -> dict[float, int]:
    by_strike: dict[float, int] = defaultdict(int)
    for c in contracts:
        if c.option_type.upper() != side:
            continue
        oi = c.open_interest or 0
        if oi <= 0:
            continue
        by_strike[c.strike] += oi
    return dict(by_strike)


def _top_clusters(
    by_strike: dict[float, int],
    *,
    spot: float,
    threshold_pct: float,
    top_n: int,
) -> tuple[list[WallClusterStrike], int]:
    if not by_strike:
        return [], 0
    peak_oi = max(by_strike.values())
    if peak_oi <= 0:
        return [], 0
    cutoff = peak_oi * threshold_pct
    qualifying = [
        (strike, oi) for strike, oi in by_strike.items() if oi >= cutoff
    ]
    qualifying.sort(key=lambda pair: pair[1], reverse=True)
    rows: list[WallClusterStrike] = []
    for strike, oi in qualifying[:top_n]:
        rows.append(
            WallClusterStrike(
                strike=strike,
                oi=int(oi),
                oi_pct_of_peak=oi / peak_oi,
                distance_pct=((strike - spot) / spot) if spot > 0 else None,
            )
        )
    return rows, peak_oi


def detect_wall_clusters(
    *,
    ticker: str,
    spot: float,
    contracts: list[OptionContract],
    today: date | None = None,
    threshold_pct: float = CLUSTER_OI_THRESHOLD,
    top_n: int = DEFAULT_TOP_N,
    buckets: tuple[TenorBucketSpec, ...] = BUCKETS,
) -> WallClusters:
    """Bucket the chain by DTE and return per-bucket call/put clusters.

    Args:
        ticker: Symbol, just round-tripped into the result.
        spot: Underlying spot price; used for distance_pct.
        contracts: Full chain (all expiries already merged in).
        today: Reference date for DTE math. Defaults to date.today();
            tests pass a fixed date so they're not calendar-dependent.
        threshold_pct: Min OI share of bucket peak to count as a cluster.
        top_n: How many clusters per side per bucket to surface.
        buckets: Tenor specs. Defaults to 0-7 / 8-30 / 31+.

    Empty chains return an empty buckets list (no error).
    """
    today_d = today or date.today()
    grouped: dict[str, list[OptionContract]] = {b.label: [] for b in buckets}
    for c in contracts:
        dte = (c.expiry - today_d).days
        spec = _bucket_for(dte, buckets)
        if spec is None:
            continue
        grouped[spec.label].append(c)

    bucket_rows: list[WallClusterBucket] = []
    for spec in buckets:
        members = grouped[spec.label]
        calls_by_strike = _aggregate_oi_by_strike(members, "C")
        puts_by_strike = _aggregate_oi_by_strike(members, "P")
        top_calls, peak_call = _top_clusters(
            calls_by_strike, spot=spot, threshold_pct=threshold_pct, top_n=top_n
        )
        top_puts, peak_put = _top_clusters(
            puts_by_strike, spot=spot, threshold_pct=threshold_pct, top_n=top_n
        )
        bucket_rows.append(
            WallClusterBucket(
                label=spec.label,
                dte_min=spec.dte_min,
                dte_max=spec.dte_max,
                contract_count=len(members),
                peak_call_oi=peak_call,
                peak_put_oi=peak_put,
                top_calls=top_calls,
                top_puts=top_puts,
            )
        )

    return WallClusters(
        ticker=ticker.upper(),
        spot=spot,
        threshold_pct=threshold_pct,
        top_n=top_n,
        buckets=bucket_rows,
    )
