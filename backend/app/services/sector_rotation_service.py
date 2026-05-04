"""Sector rotation service — fetches the 11 GICS SPDR ETFs from yfinance.

We fetch one year of daily bars per ETF in a single yfinance.download call.
The 1-year window covers every supported return window (1d / 5d / 1m / 3m
/ YTD) for any reasonable point in the calendar.

The result is cached for 15 minutes — sector rotation is intra-day at best,
not tick-by-tick, so a fresh pull every 15 min is plenty.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services.network_utils import run_sync_with_retries
from core.sector_rotation import (
    RETURN_WINDOWS,
    SECTOR_ETFS,
    compute_rotation,
)

logger = logging.getLogger(__name__)


_CACHE_TTL = timedelta(minutes=15)
_cache: tuple[datetime, dict[str, Any]] | None = None


def _download_blocking(symbols: list[str]) -> dict[str, list[tuple[date, float]]]:
    """yfinance.download for a basket; returns {symbol → ascending bars}.

    Failures for any one symbol are logged and that symbol is omitted —
    the rotation page can still render the rest with the missing one
    showing all-None returns.
    """
    import yfinance as yf

    series: dict[str, list[tuple[date, float]]] = {}
    try:
        frame = yf.download(
            tickers=" ".join(symbols),
            period="1y",
            interval="1d",
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance.download failed for sectors: %s", exc)
        return series

    if frame is None or getattr(frame, "empty", True):
        return series

    for symbol in symbols:
        try:
            # Multi-symbol downloads return a column-multiindex frame. For a
            # single-symbol fallback the frame is flat — handle both.
            if symbol in getattr(frame.columns, "levels", [[]])[0]:
                sub = frame[symbol]
            else:
                sub = frame
            if "Close" not in sub.columns:
                continue
            closes = sub["Close"].dropna()
            bars: list[tuple[date, float]] = []
            for idx, val in closes.items():
                d = idx.date() if hasattr(idx, "date") else idx
                try:
                    c = float(val)
                except (TypeError, ValueError):
                    continue
                if c <= 0:
                    continue
                bars.append((d, c))
            bars.sort(key=lambda pair: pair[0])
            if bars:
                series[symbol] = bars
        except Exception as exc:  # noqa: BLE001
            logger.debug("sector parse failed for %s: %s", symbol, exc)
            continue

    return series


async def get_sector_rotation(*, force: bool = False) -> dict[str, Any]:
    """Return the rotation matrix payload, hitting yfinance at most every 15 min."""
    global _cache

    now = datetime.now(timezone.utc)
    if not force and _cache is not None and now - _cache[0] <= _CACHE_TTL:
        return _cache[1]

    symbols = [s.symbol for s in SECTOR_ETFS]
    series = await run_sync_with_retries(_download_blocking, symbols)
    sectors_input = [(s.symbol, s.sector) for s in SECTOR_ETFS]
    snapshot = compute_rotation(
        series_by_symbol=series,
        sectors=sectors_input,
    )

    payload = {
        "windows": [label for label, _ in RETURN_WINDOWS],
        "rows": [
            {
                "symbol": r.symbol,
                "sector": r.sector,
                "latest_close": r.latest_close,
                "latest_date": r.latest_date,
                "returns": r.returns,
                "ranks": r.ranks,
                "rank_change_5d_vs_1m": r.rank_change_5d_vs_1m,
            }
            for r in snapshot.rows
        ],
        "as_of": snapshot.as_of,
        "generated_at": now,
    }
    _cache = (now, payload)
    return payload
