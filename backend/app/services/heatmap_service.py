"""S&P-style heatmap tiles + 11-sector aggregate view.

Reuses the curated 55-name universe from `core.screener.universe`
(5 names per GICS sector) to avoid maintaining a separate ticker list.
A future task can swap the universe for a 500-name constituents file
without changing this module.

The 1-day change is computed from yfinance daily bars (`period="5d"`,
`interval="1d"`, take the last two closes — the wider window keeps us
safe over weekends + holidays). Market cap comes from yfinance
`.info["marketCap"]` per symbol — slower per call but only fetched
once per 15-minute cache window.

Tile colour-mapping is the frontend's job: we ship the raw fraction
(0.012 for +1.2%) and let the UI choose its colour ramp.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.network_utils import run_sync_with_retries
from core.screener import SCREENER_UNIVERSE

logger = logging.getLogger(__name__)


_CACHE_TTL = timedelta(minutes=15)
_cache: tuple[datetime, dict[str, Any]] | None = None


def _reset_cache() -> None:
    """Test helper."""
    global _cache
    _cache = None


def _flat_universe() -> list[tuple[str, str]]:
    """[(symbol, sector), ...] — flat view of the screener universe."""
    return [(entry.symbol, entry.sector) for entry in SCREENER_UNIVERSE]


def _download_blocking(symbols: list[str]) -> dict[str, Any]:
    """Bulk-fetch 5-day bars + per-symbol .info marketCap.

    Returns:
        {
            "closes_by_symbol": {sym: [close_yesterday, close_today]},
            "market_cap_by_symbol": {sym: float},
        }
    """
    import yfinance as yf

    closes_by_symbol: dict[str, list[float]] = {}
    market_cap_by_symbol: dict[str, float] = {}

    if not symbols:
        return {
            "closes_by_symbol": closes_by_symbol,
            "market_cap_by_symbol": market_cap_by_symbol,
        }

    # 5-day daily bars — gives us yesterday + today closes for the 1d
    # change. period="5d" so weekends + holidays don't leave us with a
    # single bar.
    try:
        frame = yf.download(
            tickers=" ".join(symbols),
            period="5d",
            interval="1d",
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("heatmap: yfinance.download failed: %s", exc)
        frame = None

    if frame is not None and not getattr(frame, "empty", True):
        for sym in symbols:
            try:
                if sym in getattr(frame.columns, "levels", [[]])[0]:
                    sub = frame[sym]
                else:
                    sub = frame
                if "Close" not in sub.columns:
                    continue
                closes = [float(v) for v in sub["Close"].dropna().tolist() if v]
                if len(closes) >= 2:
                    closes_by_symbol[sym] = closes[-2:]
                elif len(closes) == 1:
                    closes_by_symbol[sym] = closes[-1:]
            except Exception as exc:  # noqa: BLE001
                logger.debug("heatmap: close parse failed for %s: %s", sym, exc)
                continue

    # Per-symbol .info marketCap.
    for sym in symbols:
        try:
            info = yf.Ticker(sym).info or {}
            cap = info.get("marketCap")
            if cap is not None:
                market_cap_by_symbol[sym] = float(cap)
        except Exception as exc:  # noqa: BLE001
            logger.debug("heatmap: marketCap fetch failed for %s: %s", sym, exc)
            continue

    return {
        "closes_by_symbol": closes_by_symbol,
        "market_cap_by_symbol": market_cap_by_symbol,
    }


def _compute_change_pct(closes: list[float]) -> float | None:
    """Return (today / yesterday) - 1, or None when not enough data."""
    if len(closes) < 2:
        return None
    yesterday, today = closes[-2], closes[-1]
    if yesterday <= 0:
        return None
    return (today / yesterday) - 1.0


def _build_payload(
    raw: dict[str, Any], universe: list[tuple[str, str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pure compute: turn the fetched data into symbol tiles + sector aggregate."""
    closes_by_symbol = raw.get("closes_by_symbol", {})
    market_cap_by_symbol = raw.get("market_cap_by_symbol", {})

    tiles: list[dict[str, Any]] = []
    for symbol, sector in universe:
        closes = closes_by_symbol.get(symbol) or []
        change = _compute_change_pct(closes)
        latest_close = closes[-1] if closes else None
        tiles.append(
            {
                "symbol": symbol,
                "sector": sector,
                "market_cap": market_cap_by_symbol.get(symbol),
                "change_1d_pct": change,
                "latest_close": latest_close,
            }
        )

    # Sector aggregate: market-cap-weighted change.
    sector_rows: dict[str, dict[str, Any]] = {}
    for tile in tiles:
        sector = tile["sector"]
        if sector not in sector_rows:
            sector_rows[sector] = {
                "sector": sector,
                "total_market_cap": 0.0,
                "_weighted_change_numerator": 0.0,
                "_weighted_change_denominator": 0.0,
                "constituent_count": 0,
            }
        row = sector_rows[sector]
        row["constituent_count"] += 1
        cap = tile.get("market_cap")
        change = tile.get("change_1d_pct")
        if cap is not None:
            row["total_market_cap"] += cap
        # Weighted change requires BOTH cap and change.
        if cap is not None and change is not None:
            row["_weighted_change_numerator"] += cap * change
            row["_weighted_change_denominator"] += cap

    sectors: list[dict[str, Any]] = []
    for sector, row in sector_rows.items():
        denom = row["_weighted_change_denominator"]
        weighted = (
            row["_weighted_change_numerator"] / denom if denom > 0 else None
        )
        sectors.append(
            {
                "sector": sector,
                "total_market_cap": (
                    row["total_market_cap"] if row["total_market_cap"] > 0 else None
                ),
                "change_1d_pct": weighted,
                "constituent_count": row["constituent_count"],
            }
        )
    sectors.sort(key=lambda r: r["sector"])
    return tiles, sectors


async def _refresh_cache() -> dict[str, Any]:
    universe = _flat_universe()
    symbols = [sym for sym, _ in universe]
    raw = await run_sync_with_retries(_download_blocking, symbols)
    tiles, sectors = _build_payload(raw, universe)
    now = datetime.now(timezone.utc)
    payload = {
        "generated_at": now,
        "as_of": now,
        "tiles": tiles,
        "sectors": sectors,
    }
    return payload


async def get_heatmap(*, force: bool = False) -> dict[str, Any]:
    """Return the joint payload (tiles + sectors). 15-minute cache."""
    global _cache
    now = datetime.now(timezone.utc)
    if not force and _cache is not None and now - _cache[0] <= _CACHE_TTL:
        return _cache[1]
    payload = await _refresh_cache()
    _cache = (now, payload)
    return payload


async def get_symbol_heatmap(*, force: bool = False) -> dict[str, Any]:
    payload = await get_heatmap(force=force)
    return {
        "items": payload["tiles"],
        "generated_at": payload["generated_at"],
        "as_of": payload["as_of"],
    }


async def get_sector_heatmap(*, force: bool = False) -> dict[str, Any]:
    payload = await get_heatmap(force=force)
    return {
        "items": payload["sectors"],
        "generated_at": payload["generated_at"],
        "as_of": payload["as_of"],
    }
