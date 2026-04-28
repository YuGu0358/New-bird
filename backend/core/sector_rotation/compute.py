"""Sector rotation math — pure compute, no I/O.

Inputs are per-symbol daily close series (already sorted ascending). Outputs
are per-symbol returns across five windows plus an integer rank within each
window, plus a rank-change signal (5d rank vs 1m rank) so the UI can draw
"moving up / moving down" arrows without rederiving anything.

Trading days vs calendar days
-----------------------------
The 5d / 1m / 3m windows count *trading-day offsets* from the latest bar
(idx-5 / idx-21 / idx-63). YTD walks back to the first bar whose date falls
inside the latest bar's calendar year. That matches how Bloomberg's MEMB
panel computes these; calendar-day arithmetic for short windows would
silently jump weekends and produce wrong returns when the data has gaps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable


# (label, trading-day offset). YTD is special-cased because it depends on
# the latest bar's calendar year.
RETURN_WINDOWS: tuple[tuple[str, int | None], ...] = (
    ("1d", 1),
    ("5d", 5),
    ("1m", 21),
    ("3m", 63),
    ("ytd", None),
)


@dataclass
class SectorRow:
    symbol: str
    sector: str
    latest_close: float | None
    latest_date: date | None
    returns: dict[str, float | None] = field(default_factory=dict)
    ranks: dict[str, int | None] = field(default_factory=dict)
    # 5d rank minus 1m rank. Negative = sector improving recently
    # (lower rank number = better return). None when either rank missing.
    rank_change_5d_vs_1m: int | None = None


@dataclass
class SectorSnapshot:
    rows: list[SectorRow] = field(default_factory=list)
    as_of: date | None = None


def compute_returns(
    bars: list[tuple[date, float]],
) -> tuple[dict[str, float | None], date | None, float | None]:
    """Compute the 5 windowed returns from a daily close series.

    `bars` must be sorted ascending by date with no NaN closes. Closes ≤ 0
    are treated as missing for the return that anchors on them.

    Returns (returns_dict, latest_date, latest_close).
    """
    if not bars:
        return ({label: None for label, _ in RETURN_WINDOWS}, None, None)

    latest_date, latest_close = bars[-1]
    if latest_close is None or latest_close <= 0:
        return ({label: None for label, _ in RETURN_WINDOWS}, latest_date, None)

    out: dict[str, float | None] = {}
    n = len(bars)

    for label, offset in RETURN_WINDOWS:
        if label == "ytd":
            # First bar inside the latest year. If the series starts mid-year
            # the first bar wins (that's the closest we can get).
            anchor_close: float | None = None
            for d, c in bars:
                if d.year == latest_date.year and c and c > 0:
                    anchor_close = c
                    break
            if anchor_close is None:
                out[label] = None
                continue
            out[label] = (latest_close / anchor_close) - 1.0
            continue

        if offset is None:  # defensive — won't happen with current spec
            out[label] = None
            continue

        if n <= offset:
            out[label] = None
            continue
        anchor = bars[n - 1 - offset][1]
        if anchor is None or anchor <= 0:
            out[label] = None
            continue
        out[label] = (latest_close / anchor) - 1.0

    return out, latest_date, latest_close


def _ranks_for_window(
    rows: Iterable[SectorRow], window: str
) -> dict[str, int]:
    """Rank symbols by descending return for one window.

    Rank 1 = best (highest return). Symbols with None return for the
    window are excluded from the ranking entirely (their rank stays None).
    """
    candidates = [
        (r.symbol, r.returns.get(window))
        for r in rows
        if r.returns.get(window) is not None
    ]
    candidates.sort(key=lambda pair: pair[1], reverse=True)
    return {symbol: idx + 1 for idx, (symbol, _) in enumerate(candidates)}


def compute_rotation(
    *,
    series_by_symbol: dict[str, list[tuple[date, float]]],
    sectors: list[tuple[str, str]],
) -> SectorSnapshot:
    """Build the full rotation snapshot.

    Args:
        series_by_symbol: symbol → ascending list of (date, close) tuples.
            Symbols missing from this dict still get a row (returns all None).
        sectors: ordered list of (symbol, sector_label) — fixes display order.

    Returns:
        SectorSnapshot with one row per (symbol, sector) and `as_of` set to
        the most recent bar across all series (or None if no bars).
    """
    rows: list[SectorRow] = []
    latest_overall: date | None = None

    for symbol, sector_label in sectors:
        bars = series_by_symbol.get(symbol) or []
        returns, latest_d, latest_c = compute_returns(bars)
        rows.append(
            SectorRow(
                symbol=symbol,
                sector=sector_label,
                latest_close=latest_c,
                latest_date=latest_d,
                returns=returns,
            )
        )
        if latest_d and (latest_overall is None or latest_d > latest_overall):
            latest_overall = latest_d

    # Fill ranks per window across the snapshot.
    for label, _ in RETURN_WINDOWS:
        ranks = _ranks_for_window(rows, label)
        for r in rows:
            r.ranks[label] = ranks.get(r.symbol)

    # Short-vs-medium momentum delta.
    for r in rows:
        rank_5d = r.ranks.get("5d")
        rank_1m = r.ranks.get("1m")
        if rank_5d is None or rank_1m is None:
            r.rank_change_5d_vs_1m = None
        else:
            r.rank_change_5d_vs_1m = rank_5d - rank_1m

    return SectorSnapshot(rows=rows, as_of=latest_overall)
