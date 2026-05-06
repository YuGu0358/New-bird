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


def _fetch_quarterly_history_blocking(
    symbol: str,
) -> list[dict[str, Any]]:
    """Pull yfinance quarterly statements + history, derive per-quarter
    fundamentals as TTM rolling 4-quarter sums.

    Returns rows of the form:
      {date: filing_date, market_cap, pe_ratio, pb_ratio, eps_ttm,
       revenue_ttm, gross_margin, debt_to_equity, roe, short_interest_pct}

    Empty list when yfinance returns no quarterly data (rare — newly
    listed tickers or delisted ADRs).
    """
    try:
        import yfinance as yf  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415

        t = yf.Ticker(symbol)
        bs_q = t.quarterly_balance_sheet
        is_q = t.quarterly_income_stmt
        # 5y of close so we can compute market_cap at each filing date.
        hist = t.history(period="5y", interval="1d")
    except Exception:  # noqa: BLE001
        logger.debug("yf quarterly fetch failed for %s", symbol, exc_info=True)
        return []

    if bs_q is None or bs_q.empty or is_q is None or is_q.empty:
        return []

    # Both frames are indexed by metric (rows) × date (columns).
    quarter_dates = sorted(set(bs_q.columns).union(is_q.columns))
    if not quarter_dates:
        return []

    def _val(frame, key, col) -> float | None:
        if frame is None or frame.empty:
            return None
        # yf labels vary across data revisions; try a few aliases.
        if key not in frame.index:
            for alt in (key.replace(" ", ""), key.title(), key.upper()):
                if alt in frame.index:
                    key = alt
                    break
        if key not in frame.index or col not in frame.columns:
            return None
        v = frame.at[key, col]
        return _f(v)

    # We need shares outstanding for historical market_cap. yfinance's
    # `Ticker.get_shares_full` is paid; fall back to .info.sharesOutstanding
    # as a constant approximation. Slight under/over for buybacks/issuances
    # but accurate within ~5% for most large caps.
    info_shares = None
    try:
        info_shares = _f((t.info or {}).get("sharesOutstanding"))
    except Exception:  # noqa: BLE001
        info_shares = None

    rows: list[dict[str, Any]] = []
    # Sort ascending so we can compute TTM as rolling sum of last 4
    # entries.
    quarter_dates_asc = sorted(quarter_dates)
    revenue_q: list[float | None] = []
    gross_q: list[float | None] = []
    net_income_q: list[float | None] = []

    for q in quarter_dates_asc:
        revenue_q.append(_val(is_q, "Total Revenue", q))
        gross_q.append(_val(is_q, "Gross Profit", q))
        net_income_q.append(_val(is_q, "Net Income", q))

    def _ttm(idx: int, arr: list[float | None]) -> float | None:
        window = arr[max(0, idx - 3) : idx + 1]
        vals = [v for v in window if v is not None]
        if len(vals) < 4:
            return None
        return float(sum(vals))

    for i, q in enumerate(quarter_dates_asc):
        # Derive metrics for this quarter end.
        revenue_ttm = _ttm(i, revenue_q)
        gross_ttm = _ttm(i, gross_q)
        net_income_ttm = _ttm(i, net_income_q)

        equity = _val(bs_q, "Stockholders Equity", q) or _val(
            bs_q, "Common Stock Equity", q
        )
        long_term_debt = _val(bs_q, "Long Term Debt", q) or _val(
            bs_q, "Total Debt", q
        )

        # Historical market cap: shares × close-at-filing.
        market_cap_at_filing: float | None = None
        if info_shares and not hist.empty:
            try:
                # hist index is tz-aware datetime; q is also datetime.
                # Use as-of <= q (last close on or before filing).
                ts = pd.to_datetime(q)
                if ts.tzinfo is None and hist.index.tzinfo is not None:
                    ts = ts.tz_localize(hist.index.tzinfo)
                elif hist.index.tzinfo is None and ts.tzinfo is not None:
                    ts = ts.tz_localize(None)
                # Slice up to ts and take last close.
                cutoff = hist.loc[hist.index <= ts]
                if not cutoff.empty:
                    last_close = float(cutoff["Close"].iloc[-1])
                    market_cap_at_filing = info_shares * last_close
            except Exception:  # noqa: BLE001
                market_cap_at_filing = None

        pe_ratio = (
            market_cap_at_filing / net_income_ttm
            if market_cap_at_filing and net_income_ttm and net_income_ttm > 0
            else None
        )
        pb_ratio = (
            market_cap_at_filing / equity
            if market_cap_at_filing and equity and equity > 0
            else None
        )
        eps_ttm = (
            net_income_ttm / info_shares
            if net_income_ttm and info_shares and info_shares > 0
            else None
        )
        gross_margin = (
            gross_ttm / revenue_ttm
            if gross_ttm and revenue_ttm and revenue_ttm > 0
            else None
        )
        debt_to_equity = (
            long_term_debt / equity
            if long_term_debt and equity and equity > 0
            else None
        )
        roe = (
            net_income_ttm / equity
            if net_income_ttm and equity and equity > 0
            else None
        )

        # Filing date is approximated as the quarter end + 45 days
        # (typical 10-Q lag). yfinance only gives the period-end date,
        # not the filing date itself.
        from datetime import timedelta as _td  # noqa: PLC0415
        filing_date = (q.date() if hasattr(q, "date") else q) + _td(days=45)

        rows.append(
            {
                "date": filing_date,
                "market_cap": market_cap_at_filing,
                "pe_ratio": pe_ratio,
                "pb_ratio": pb_ratio,
                "eps_ttm": eps_ttm,
                "revenue_ttm": revenue_ttm,
                "gross_margin": gross_margin,
                "debt_to_equity": debt_to_equity,
                "roe": roe,
                "short_interest_pct": None,
            }
        )

    return rows


async def refresh_quarterly_history(
    symbols: list[str], *, lookback_years: int = 4
) -> dict[str, int]:
    """Backfill historical fundamentals from yfinance quarterly data.

    For each symbol, pulls 4y+ of quarterly balance sheet + income
    statement, derives TTM metrics per quarter, and upserts a row at
    each filing date (≈ quarter end + 45 days). 16 rows per symbol;
    100 symbols ≈ 1600 rows; refresh runtime ≈ 5-10 min.

    Returns ``{"symbols_attempted": N, "rows_written": M}``.
    """
    if not symbols:
        return {"symbols_attempted": 0, "rows_written": 0}
    written = 0
    for sym in symbols:
        per_symbol_rows = await asyncio.to_thread(
            _fetch_quarterly_history_blocking, sym
        )
        if not per_symbol_rows:
            continue
        rows = [
            {
                "symbol": sym,
                "date": r["date"],
                "refreshed_at": datetime.now(timezone.utc),
                "market_cap": r["market_cap"],
                "pe_ratio": r["pe_ratio"],
                "pb_ratio": r["pb_ratio"],
                "eps_ttm": r["eps_ttm"],
                "revenue_ttm": r["revenue_ttm"],
                "gross_margin": r["gross_margin"],
                "debt_to_equity": r["debt_to_equity"],
                "roe": r["roe"],
                "short_interest_pct": r["short_interest_pct"],
            }
            for r in per_symbol_rows
        ]
        update_cols = {
            c.name: None for c in FactorDailyFundamentals.__table__.columns
            if c.name not in {"symbol", "date"}
        }
        async with AsyncSessionLocal() as session:
            try:
                for i in range(0, len(rows), _BATCH_BAR):
                    batch = rows[i : i + _BATCH_BAR]
                    stmt = sqlite_insert(FactorDailyFundamentals).values(batch)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["symbol", "date"],
                        set_={col: stmt.excluded[col] for col in update_cols},
                    )
                    await session.execute(stmt)
                    written += len(batch)
                await session.commit()
            except Exception:
                logger.warning(
                    "quarterly history upsert failed for %s", sym, exc_info=True
                )
                await session.rollback()
    logger.info(
        "quarterly history: wrote %d rows across %d symbols", written, len(symbols)
    )
    return {"symbols_attempted": len(symbols), "rows_written": written}


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
