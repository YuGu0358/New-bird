"""Screener service — yfinance enrichment + 1-hour cache.

Mirrors `sector_rotation_service`'s caching shape: one cache slot for the
whole 55-name universe, refreshed at most once per hour. Filter / sort /
paginate is delegated to `core.screener.compute` — this module is purely
I/O and orchestration.

Two-step fetch
--------------
1. Single `yfinance.download(period="3mo")` for closes → derive
   `momentum_3m` and `latest_close` for every symbol.
2. Per-symbol `.info` calls for `marketCap`, `trailingPE`, `pegRatio`,
   `revenueGrowth`. Wrapped in try/except per symbol; failures degrade
   to None for that symbol's metric fields (the row still appears in the
   universe).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.network_utils import run_sync_with_retries
from core.screener import (
    SCREENER_UNIVERSE,
    ScreenerFilter,
    ScreenerRow,
    apply_filter,
    sort_and_paginate,
)

logger = logging.getLogger(__name__)


_CACHE_TTL = timedelta(hours=1)
# (cached_at, {rows: list[ScreenerRow], as_of: datetime | None})
_cache: tuple[datetime, dict[str, Any]] | None = None


def _build_universe_blocking(symbols: list[str]) -> dict[str, Any]:
    """Fetch closes (one bulk download) + per-symbol .info, return enriched rows.

    Returns: {"rows": list[ScreenerRow], "as_of": datetime | None}.
    `as_of` is the wall-clock build time; `latest_close` carries the bar
    timestamp implicitly via the price.
    """
    import yfinance as yf

    sector_by_symbol = {e.symbol: e.sector for e in SCREENER_UNIVERSE}
    momentum: dict[str, float | None] = {s: None for s in symbols}
    latest_close: dict[str, float | None] = {s: None for s in symbols}

    # --- 1. Bulk close download for momentum + latest close. ---
    try:
        frame = yf.download(
            tickers=" ".join(symbols),
            period="3mo",
            interval="1d",
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance.download failed for screener: %s", exc)
        frame = None

    if frame is not None and not getattr(frame, "empty", True):
        for symbol in symbols:
            try:
                if symbol in getattr(frame.columns, "levels", [[]])[0]:
                    sub = frame[symbol]
                else:
                    sub = frame
                if "Close" not in sub.columns:
                    continue
                closes = sub["Close"].dropna()
                if len(closes) < 2:
                    if len(closes) == 1:
                        latest_close[symbol] = float(closes.iloc[-1])
                    continue
                first = float(closes.iloc[0])
                last = float(closes.iloc[-1])
                latest_close[symbol] = last
                if first > 0:
                    momentum[symbol] = (last / first) - 1.0
            except Exception as exc:  # noqa: BLE001
                logger.debug("screener close parse failed for %s: %s", symbol, exc)
                continue

    # --- 2. Per-symbol .info for fundamentals. ---
    info_metrics: dict[str, dict[str, float | None]] = {}
    for symbol in symbols:
        market_cap: float | None = None
        pe_ratio: float | None = None
        peg_ratio: float | None = None
        rev_growth: float | None = None
        try:
            info = yf.Ticker(symbol).info or {}
            market_cap = _coerce_float(info.get("marketCap"))
            pe_ratio = _coerce_float(info.get("trailingPE"))
            peg_ratio = _coerce_float(info.get("pegRatio"))
            rev_growth = _coerce_float(info.get("revenueGrowth"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("screener .info failed for %s: %s", symbol, exc)
        info_metrics[symbol] = {
            "market_cap": market_cap,
            "pe_ratio": pe_ratio,
            "peg_ratio": peg_ratio,
            "revenue_growth": rev_growth,
        }

    rows: list[ScreenerRow] = []
    for symbol in symbols:
        metrics = info_metrics.get(symbol, {})
        rows.append(
            ScreenerRow(
                symbol=symbol,
                sector=sector_by_symbol.get(symbol, ""),
                market_cap=metrics.get("market_cap"),
                pe_ratio=metrics.get("pe_ratio"),
                peg_ratio=metrics.get("peg_ratio"),
                revenue_growth=metrics.get("revenue_growth"),
                momentum_3m=momentum.get(symbol),
                latest_close=latest_close.get(symbol),
            )
        )

    return {"rows": rows, "as_of": datetime.now(timezone.utc)}


def _coerce_float(value: Any) -> float | None:
    """yfinance .info sometimes returns int, NaN, None, or str — normalize."""
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


async def _get_cached_universe(*, force: bool) -> dict[str, Any]:
    """Return (and refresh if needed) the cached enriched universe."""
    global _cache

    now = datetime.now(timezone.utc)
    if not force and _cache is not None and now - _cache[0] <= _CACHE_TTL:
        return _cache[1]

    symbols = [e.symbol for e in SCREENER_UNIVERSE]
    payload = await run_sync_with_retries(_build_universe_blocking, symbols)
    _cache = (now, payload)
    return payload


def _row_to_dict(row: ScreenerRow) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "sector": row.sector,
        "market_cap": row.market_cap,
        "pe_ratio": row.pe_ratio,
        "peg_ratio": row.peg_ratio,
        "revenue_growth": row.revenue_growth,
        "momentum_3m": row.momentum_3m,
        "latest_close": row.latest_close,
    }


async def search(
    *,
    spec: ScreenerFilter,
    sort_by: str,
    descending: bool,
    page: int,
    page_size: int,
    force: bool = False,
) -> dict[str, Any]:
    """Run filter/sort/paginate against the cached enriched universe.

    Returns:
        {rows, total, page, page_size, sort_by, descending, generated_at, as_of}
        with `rows` as a list of dicts and `as_of` as the cache-build
        timestamp.
    """
    payload = await _get_cached_universe(force=force)
    universe_rows: list[ScreenerRow] = payload.get("rows", [])
    as_of: datetime | None = payload.get("as_of")

    filtered = apply_filter(universe_rows, spec)
    page_rows, total = sort_and_paginate(
        filtered,
        sort_by=sort_by,
        descending=descending,
        page=page,
        page_size=page_size,
    )

    return {
        "rows": [_row_to_dict(r) for r in page_rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "sort_by": sort_by,
        "descending": descending,
        "generated_at": datetime.now(timezone.utc),
        "as_of": as_of,
    }
