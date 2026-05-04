"""Pure compute helpers over CoinGecko `/coins/markets` payloads.

`parse_markets_payload` is purely defensive: it never raises on malformed
upstream data, instead skipping the offending row and returning what it
could parse. Missing optional keys map to None.

`sort_and_limit` provides a stable sort with None values always last
regardless of direction, plus a deterministic tie-break (rank asc, then
symbol asc) so identical sort keys don't flicker between requests.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


SORTABLE_COLUMNS: tuple[str, ...] = (
    "market_cap_usd",
    "volume_24h_usd",
    "change_24h_pct",
    "rank",
    "price_usd",
)


@dataclass
class CryptoMarketRow:
    """A single normalized CoinGecko market row.

    `change_24h_pct` is stored as a fraction (0.05 = 5%), even though the
    upstream feed serves it as a percent value. Conversion happens in
    `parse_markets_payload`, so consumers downstream always see the
    fraction form.
    """

    coin_id: str
    symbol: str
    name: str
    rank: int | None
    price_usd: float
    market_cap_usd: float | None
    volume_24h_usd: float | None
    change_24h_pct: float | None
    image_url: str | None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    # NaN guard: NaN != NaN.
    if out != out:
        return None
    return out


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_one(item: dict) -> CryptoMarketRow | None:
    """Parse a single CoinGecko market row, returning None if unusable.

    The four mandatory fields are `id`, `symbol`, `name`, `current_price`.
    Anything else may be missing or null — they degrade to None on the row.
    """
    coin_id = _coerce_str(item.get("id"))
    symbol_raw = _coerce_str(item.get("symbol"))
    name = _coerce_str(item.get("name"))
    price_usd = _coerce_float(item.get("current_price"))

    if coin_id is None or symbol_raw is None or name is None or price_usd is None:
        return None

    pct_raw = _coerce_float(item.get("price_change_percentage_24h"))
    change_24h_pct = pct_raw / 100.0 if pct_raw is not None else None

    return CryptoMarketRow(
        coin_id=coin_id,
        symbol=symbol_raw.upper(),
        name=name,
        rank=_coerce_int(item.get("market_cap_rank")),
        price_usd=price_usd,
        market_cap_usd=_coerce_float(item.get("market_cap")),
        volume_24h_usd=_coerce_float(item.get("total_volume")),
        change_24h_pct=change_24h_pct,
        image_url=_coerce_str(item.get("image")),
    )


def parse_markets_payload(items: list[dict]) -> list[CryptoMarketRow]:
    """Defensive parser for CoinGecko's `/coins/markets` shape.

    - Skips malformed rows entirely (DEBUG-logs the count once at the end)
      rather than raising.
    - Handles missing optional keys by setting them to None.
    - Converts `price_change_percentage_24h` from a percent value to a
      fraction (5.5 → 0.055).
    """
    rows: list[CryptoMarketRow] = []
    skipped = 0

    for item in items or []:
        if not isinstance(item, dict):
            skipped += 1
            continue
        parsed = _parse_one(item)
        if parsed is None:
            skipped += 1
            continue
        rows.append(parsed)

    if skipped:
        logger.debug(
            "parse_markets_payload skipped %d malformed rows of %d", skipped, len(items or [])
        )
    return rows


def _sort_key_for(row: CryptoMarketRow, sort_by: str) -> Any:
    return getattr(row, sort_by)


def sort_and_limit(
    rows: list[CryptoMarketRow],
    *,
    limit: int = 100,
    sort_by: str = "volume_24h_usd",
    descending: bool = True,
) -> list[CryptoMarketRow]:
    """Stable sort + top-N trim.

    None values always sort last regardless of direction. Ties on the
    primary sort key break on `rank` ascending, then `symbol` ascending,
    so the order is fully deterministic.

    `limit` is clamped to [1, 250]. Unknown `sort_by` raises ValueError.
    """
    if sort_by not in SORTABLE_COLUMNS:
        raise ValueError(
            f"Unknown sort_by={sort_by!r}; allowed: {', '.join(SORTABLE_COLUMNS)}"
        )

    clamped_limit = max(1, min(int(limit), 250))

    def primary_key(row: CryptoMarketRow) -> tuple[int, float]:
        """(none-flag, value-for-comparison). None always sorts last."""
        value = _sort_key_for(row, sort_by)
        if value is None:
            # When descending, Python sorts large→small; we still want None
            # last, so we return (1, 0.0) and rely on the explicit None-flag
            # being compared first.
            return (1, 0.0)
        # Treat all numeric/comparable types uniformly as float.
        return (0, float(value))

    def tie_break_key(row: CryptoMarketRow) -> tuple[int, str]:
        rank_for_tie = row.rank if row.rank is not None else 10**9
        return (rank_for_tie, row.symbol)

    if descending:
        # Sort by primary desc, then tie-break asc. Achieve this with a
        # two-pass stable sort: first apply tie-break asc, then primary desc.
        intermediate = sorted(rows, key=tie_break_key)
        sorted_rows = sorted(
            intermediate,
            key=lambda r: (primary_key(r)[0], -primary_key(r)[1]),
        )
    else:
        intermediate = sorted(rows, key=tie_break_key)
        sorted_rows = sorted(
            intermediate,
            key=lambda r: (primary_key(r)[0], primary_key(r)[1]),
        )

    return sorted_rows[:clamped_limit]
