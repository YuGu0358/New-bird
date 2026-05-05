"""Daily fundamentals refresh — yfinance ``Ticker.info`` snapshot.

Polygon's free tier rate-limits at 5 req/min, which only filled 10/100
symbols on the first refresh attempt. yfinance has no hard limit and
returns all the fundamentals we need in a single ``Ticker(sym).info``
call — marketCap, trailingPE, priceToBook, returnOnEquity, debtToEquity,
grossMargins, totalRevenue, trailingEps, shortPercentOfFloat.

Per-symbol ~1-2 sec wall time, so 100 symbols ≈ 2-3 min. We chunk-write
in batches of 500 rows to stay under SQLite's bound-variable cap.

Forward-fill of quarterly data into daily rows is handled at panel-load
time in ``factor_data_service.get_panel`` — this service just snapshots
"as of today" per symbol per refresh.

short_interest_pct comes from the same yfinance call (``shortPercentOfFloat``)
so we no longer need a separate Phase 3.4 service for it.

Refresh cadence: daily, after market close, alongside the bar refresh.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.engine import AsyncSessionLocal
from app.db.tables import FactorDailyFundamentals

logger = logging.getLogger(__name__)


_BATCH_BAR = 500  # chunk size for INSERT/UPSERT — same SQLite cap as DailyBar


def _f(v: Any) -> float | None:
    """Coerce yfinance.info value to float | None. yfinance returns
    floats, ints, or sometimes strings/None; some metrics come back as
    NaN-as-string for missing data."""
    if v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _fetch_one_blocking(symbol: str) -> dict[str, float | None]:
    """Pull yfinance.info for one ticker, derive our 9 fundamental fields.

    yfinance.info field map:
      marketCap            → market_cap
      trailingPE           → pe_ratio
      priceToBook          → pb_ratio
      trailingEps          → eps_ttm
      totalRevenue         → revenue_ttm
      grossMargins         → gross_margin (already a fraction in [0,1])
      debtToEquity         → debt_to_equity (yf reports as percent: 110.5
                             means 1.105; divide by 100)
      returnOnEquity       → roe (already a fraction)
      shortPercentOfFloat  → short_interest_pct (already a fraction)
    """
    try:
        import yfinance as yf  # noqa: PLC0415

        info = yf.Ticker(symbol).info or {}
    except Exception:  # noqa: BLE001 — yfinance throws weirdly; treat as missing
        logger.debug("yfinance.info failed for %s", symbol, exc_info=True)
        return {
            "market_cap": None,
            "pe_ratio": None,
            "pb_ratio": None,
            "eps_ttm": None,
            "revenue_ttm": None,
            "gross_margin": None,
            "debt_to_equity": None,
            "roe": None,
            "short_interest_pct": None,
        }

    de_raw = _f(info.get("debtToEquity"))
    return {
        "market_cap": _f(info.get("marketCap")),
        "pe_ratio": _f(info.get("trailingPE")),
        "pb_ratio": _f(info.get("priceToBook")),
        "eps_ttm": _f(info.get("trailingEps")),
        "revenue_ttm": _f(info.get("totalRevenue")),
        "gross_margin": _f(info.get("grossMargins")),
        # yfinance returns debtToEquity as a percent figure (e.g. 110.5
        # for 1.105×). Normalise to a ratio.
        "debt_to_equity": (de_raw / 100.0) if de_raw is not None else None,
        "roe": _f(info.get("returnOnEquity")),
        "short_interest_pct": _f(info.get("shortPercentOfFloat")),
    }


async def refresh_fundamentals(
    symbols: list[str], *, target_date: date | None = None
) -> int:
    """Refresh and persist fundamentals for ``symbols`` on ``target_date``
    (defaults to today). Returns the number of rows written.

    Per-symbol fetch is yfinance (~1-2s wall time each), run via
    ``asyncio.to_thread`` so the event loop stays responsive. 100
    symbols ≈ 2-3 min total.
    """
    if not symbols:
        return 0
    target = target_date or datetime.now(timezone.utc).date()
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        metrics = await asyncio.to_thread(_fetch_one_blocking, sym)
        row = {
            "symbol": sym,
            "date": target,
            "refreshed_at": datetime.now(timezone.utc),
            **metrics,
        }
        rows.append(row)

    if not rows:
        return 0

    inserted = 0
    update_cols = {
        c.name: None for c in FactorDailyFundamentals.__table__.columns
        if c.name not in {"symbol", "date"}
    }
    async with AsyncSessionLocal() as session:
        for i in range(0, len(rows), _BATCH_BAR):
            batch = rows[i : i + _BATCH_BAR]
            stmt = sqlite_insert(FactorDailyFundamentals).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "date"],
                set_={col: stmt.excluded[col] for col in update_cols},
            )
            try:
                await session.execute(stmt)
                inserted += len(batch)
            except Exception:
                logger.warning(
                    "fundamentals upsert batch failed (after %d rows)",
                    inserted, exc_info=True,
                )
                await session.rollback()
                return inserted
        await session.commit()
    logger.info(
        "fundamentals: refreshed %d symbols for %s", inserted, target.isoformat()
    )
    return inserted


async def get_fundamentals_panel(
    start: date, end: date, symbols: list[str] | None = None
):
    """Load (date, symbol)-indexed fundamentals DataFrame for the date
    range. Forward-fills missing dates per symbol so backtest panels
    that reach back farther than the refresh history still see the
    most-recent known value.

    Returns a pandas DataFrame; empty when the table has no rows in
    the requested range.
    """
    import pandas as pd  # noqa: PLC0415

    async with AsyncSessionLocal() as session:
        q = select(FactorDailyFundamentals).where(
            FactorDailyFundamentals.date >= start,
            FactorDailyFundamentals.date <= end,
        )
        if symbols is not None:
            sym_list = list(symbols)
            if not sym_list:
                return pd.DataFrame()
            q = q.where(FactorDailyFundamentals.symbol.in_(sym_list))
        rows = (await session.execute(q)).scalars().all()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "symbol": r.symbol,
                "market_cap": r.market_cap,
                "pe_ratio": r.pe_ratio,
                "pb_ratio": r.pb_ratio,
                "eps_ttm": r.eps_ttm,
                "revenue_ttm": r.revenue_ttm,
                "gross_margin": r.gross_margin,
                "debt_to_equity": r.debt_to_equity,
                "roe": r.roe,
                "short_interest_pct": r.short_interest_pct,
            }
            for r in rows
        ]
    )
    df = df.set_index(["date", "symbol"]).sort_index()
    df = df.groupby(level="symbol").ffill()
    return df
