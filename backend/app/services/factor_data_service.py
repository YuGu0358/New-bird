"""Factor Forge data ingest — pulls Russell 1000 daily bars from Alpaca,
stores them in factor_daily_bars, and computes a per-day top-100 active
universe to drive the factor mining pipeline.

Public API:
    update_daily_bars(symbols=None) -> int
    update_active_universe(target_date, top_n=100) -> int
    get_panel(start, end, symbols=None) -> pd.DataFrame
    get_active_universe(target_date, top_n=100) -> list[str]
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select

from app import runtime_settings
from app.db.engine import AsyncSessionLocal
from app.db.tables import DailyActiveUniverse, DailyBar

logger = logging.getLogger(__name__)


# Russell 1000 list — for MVP, hard-code top ~200 most-traded US tickers as a
# proxy. Production should fetch the live list from iShares IWB holdings CSV
# or polygon. For now, embed a static list (expandable).
RUSSELL_PROXY_SYMBOLS: list[str] = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "BRK.B", "AVGO",
    "JPM", "LLY", "V", "XOM", "MA", "UNH", "COST", "HD", "PG", "JNJ",
    "NFLX", "BAC", "ABBV", "CRM", "WMT", "CVX", "MRK", "ORCL", "AMD", "PEP",
    "ADBE", "KO", "TMO", "MCD", "CSCO", "PFE", "ACN", "ABT", "LIN", "WFC",
    "DIS", "DHR", "INTC", "VZ", "PM", "INTU", "TXN", "CMCSA", "QCOM", "NEE",
    "IBM", "GE", "AMGN", "UNP", "BX", "RTX", "T", "AMAT", "HON", "GS",
    "ISRG", "SPGI", "LOW", "BLK", "PGR", "BKNG", "ELV", "CAT", "MS", "LMT",
    "DE", "TJX", "AXP", "ADP", "SYK", "VRTX", "BA", "C", "MDT", "CB",
    "GILD", "AMT", "MMC", "MO", "PLD", "NOW", "ADI", "REGN", "BSX", "SBUX",
    "FI", "ZTS", "EOG", "DUK", "PYPL", "CME", "EQIX", "KKR", "BMY", "TMUS",
    "PNC", "ICE", "CDNS", "TGT", "PANW", "USB", "ITW", "WM", "SLB", "GD",
    "FDX", "MNST", "CTAS", "ANET", "CI", "MAR", "F", "GM", "HUM", "FCX",
    "ATVI", "CMG", "ECL", "ADSK", "AON", "MPC", "BDX", "NOC", "SCHW", "TRV",
    "AIG", "ROP", "AFL", "EMR", "TFC", "PSX", "MMM", "AEP", "CL", "WELL",
    "NSC", "STZ", "OXY", "MCK", "EL", "AZO", "WMB", "VLO", "PSA", "TT",
    "EW", "PXD", "MET", "FIS", "JCI", "EXC", "TEL", "ALL", "DXCM", "DOW",
    "PCAR", "FTNT", "PRU", "AMP", "ROST", "LRCX", "MU", "EA", "CNC", "ORLY",
    "BIIB", "OKE", "KMB", "NEM", "ABNB", "DG", "DLR", "RSG", "CTVA", "GIS",
    "SRE", "TRGP", "MDLZ", "FAST", "WBA", "CTSH", "CRH", "DD", "ODFL", "MRVL",
    "EBAY", "SYY", "AVB", "VICI", "CAH", "MTB", "DLTR", "URI", "OTIS", "GLW",
]

# Alpaca's bars endpoint accepts up to ~200 symbols per request; chunk to keep
# the URL/payload safe and to spread retries over smaller failure domains.
ALPACA_SYMBOL_CHUNK = 100


# ---------------------------------------------------------------------------
# Russell 1000 universe — fetched from iShares IWB holdings CSV with on-disk
# cache + fallback to RUSSELL_PROXY_SYMBOLS on any failure.
# ---------------------------------------------------------------------------

_RUSSELL_CACHE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "russell_1000_symbols.json"
)
_RUSSELL_CACHE_TTL_SEC = 7 * 24 * 3600  # 7 days
# NOTE: product id 239707 = iShares Russell 1000 ETF (IWB). The 239726 path
# returns IVV (S&P 500) and only ~500 holdings, which is a different fund.
_RUSSELL_URL = (
    "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IWB_holdings&dataType=fund"
)
_RUSSELL_MIN_SYMBOLS = 500  # Sanity floor — anything less means malformed CSV.


def _load_cached_russell() -> list[str] | None:
    """Read cached Russell symbols from disk if present and fresh."""
    try:
        if not _RUSSELL_CACHE_PATH.exists():
            return None
        age = time.time() - _RUSSELL_CACHE_PATH.stat().st_mtime
        if age > _RUSSELL_CACHE_TTL_SEC:
            return None
        with open(_RUSSELL_CACHE_PATH) as f:
            data = json.load(f)
        symbols = data.get("symbols") or []
        return list(symbols) if isinstance(symbols, list) else None
    except Exception:
        logger.debug("Russell cache read failed", exc_info=True)
        return None


def _fetch_russell_csv_sync() -> list[str]:
    """Pull the iShares IWB holdings CSV and parse out tickers.

    The file has ~9-10 header lines before the actual CSV; we locate the
    row whose first column is ``Ticker`` and parse from there. Symbols
    must match ``^[A-Z][A-Z0-9.-]{0,10}$`` to drop cash entries / option
    rows / other non-equity placeholders.
    """
    import csv
    import io
    import re
    import urllib.request

    req = urllib.request.Request(
        _RUSSELL_URL,
        headers={"User-Agent": "Mozilla/5.0 (FactorForge ingest)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed iShares URL
        raw = resp.read().decode("utf-8", errors="replace")

    lines = raw.splitlines()
    start_idx: int | None = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Ticker"):
            start_idx = i
            break
    if start_idx is None:
        raise RuntimeError("iShares CSV format changed — no Ticker header row")

    reader = csv.DictReader(io.StringIO("\n".join(lines[start_idx:])))
    pat = re.compile(r"^[A-Z][A-Z0-9.\-]{0,10}$")
    seen: set[str] = set()
    out: list[str] = []
    for row in reader:
        sym = (row.get("Ticker") or "").strip().upper()
        if pat.match(sym) and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


async def get_russell_universe() -> list[str]:
    """Return ~1000 Russell 1000 symbols, with on-disk 7-day cache.

    Falls back to the hand-coded ``RUSSELL_PROXY_SYMBOLS`` on any failure
    (network, parsing, short response, etc.) so the pipeline never stalls.
    """
    cached = _load_cached_russell()
    if cached:
        return cached
    try:
        symbols = await asyncio.to_thread(_fetch_russell_csv_sync)
        if len(symbols) < _RUSSELL_MIN_SYMBOLS:
            logger.warning(
                "iShares CSV returned only %d symbols — using fallback",
                len(symbols),
            )
            return list(RUSSELL_PROXY_SYMBOLS)
        _RUSSELL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_RUSSELL_CACHE_PATH, "w") as f:
            json.dump({"symbols": symbols, "fetched_at": time.time()}, f)
        logger.info("Fetched %d Russell 1000 symbols from iShares", len(symbols))
        return symbols
    except Exception:
        logger.warning(
            "Russell fetch failed, falling back to RUSSELL_PROXY_SYMBOLS",
            exc_info=True,
        )
        return list(RUSSELL_PROXY_SYMBOLS)


def _alpaca_data_client():
    """Build an Alpaca historical-data client using runtime settings.

    Imports `alpaca` lazily so test environments without the package
    can still import this module (tests mock _fetch_bars_sync).
    """
    try:
        from alpaca.data.historical import StockHistoricalDataClient
    except ImportError as exc:  # pragma: no cover - import-time guard
        raise RuntimeError("alpaca-py is not installed.") from exc

    api_key = runtime_settings.get_required_setting(
        "ALPACA_API_KEY", "ALPACA_API_KEY required"
    )
    secret_key = runtime_settings.get_required_setting(
        "ALPACA_SECRET_KEY", "ALPACA_SECRET_KEY required"
    )
    return StockHistoricalDataClient(api_key, secret_key)


def _fetch_bars_sync(symbols: list[str], start: date, end: date) -> pd.DataFrame:
    """Pull daily bars from Alpaca for ``symbols`` over [start, end].

    Returns a flat DataFrame with columns:
    symbol, date, open, high, low, close, volume, vwap.
    Empty DataFrame if Alpaca returns no rows.
    """
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = _alpaca_data_client()
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
        end=datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc),
    )
    bars = client.get_stock_bars(request)
    df = bars.df  # MultiIndex (symbol, timestamp)
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "vwap"]
        )
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    # Ensure expected columns are present even if Alpaca omits vwap.
    if "vwap" not in df.columns:
        df["vwap"] = None
    return df[["symbol", "date", "open", "high", "low", "close", "volume", "vwap"]]


def compute_activity_score(
    panel_today: pd.DataFrame, panel_history: pd.DataFrame
) -> pd.DataFrame:
    """Compute the composite activity score for one day.

    score = 0.4 * z(dollar_volume_today)
          + 0.3 * z(volume_today * |return_today|)
          + 0.3 * z(intraday_range / close_today)

    panel_today: one row per symbol for the target date with columns
        symbol, open, high, low, close, volume.
    panel_history: prior trading day's bars; needed for return. Columns
        symbol, close. May be empty (we treat returns as 0 in that case).

    Returns a DataFrame with columns: symbol, activity_score, dollar_volume,
    vol_return_score, range_score.
    """
    if panel_today.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "activity_score",
                "dollar_volume",
                "vol_return_score",
                "range_score",
            ]
        )

    if panel_history is None or panel_history.empty:
        merged = panel_today.copy()
        merged["prev_close"] = np.nan
    else:
        merged = panel_today.merge(
            panel_history[["symbol", "close"]].rename(columns={"close": "prev_close"}),
            on="symbol",
            how="left",
        )

    merged["dollar_volume"] = merged["close"] * merged["volume"]
    merged["abs_return"] = (merged["close"] - merged["prev_close"]).abs() / merged[
        "prev_close"
    ].replace(0, np.nan)
    merged["vol_return_score"] = merged["volume"] * merged["abs_return"].fillna(0)
    merged["range_score"] = (merged["high"] - merged["low"]) / merged["close"].replace(
        0, np.nan
    )
    merged["range_score"] = merged["range_score"].fillna(0)

    def _z(x: pd.Series) -> pd.Series:
        std = x.std(ddof=0)
        if not std or np.isnan(std):
            return pd.Series(0.0, index=x.index)
        s = (x - x.mean()) / std
        return s.fillna(0)

    merged["activity_score"] = (
        0.4 * _z(merged["dollar_volume"])
        + 0.3 * _z(merged["vol_return_score"])
        + 0.3 * _z(merged["range_score"])
    )
    return merged[
        ["symbol", "activity_score", "dollar_volume", "vol_return_score", "range_score"]
    ]


async def _load_last_dates(symbols: list[str]) -> dict[str, date]:
    """Return the most-recent stored bar date per requested symbol."""
    last_dates: dict[str, date] = {}
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyBar.symbol, func.max(DailyBar.date))
                .where(DailyBar.symbol.in_(symbols))
                .group_by(DailyBar.symbol)
            )
        ).all()
    for sym, last_date in rows:
        if last_date is not None:
            last_dates[sym] = last_date
    return last_dates


async def _persist_bars(records: list[dict]) -> int:
    """UPSERT bar rows (SQLite ON CONFLICT DO UPDATE). Returns count.

    Naive ``session.add`` would crash on the second run because the
    composite (symbol, date) PK already exists. SQLite's INSERT OR REPLACE
    handles the re-fetch case (e.g., the daily incremental running twice)
    without requiring caller-side dedupe.
    """
    if not records:
        return 0
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    rows: list[dict] = []
    for r in records:
        try:
            vwap_val = r.get("vwap")
            vwap_clean = (
                float(vwap_val)
                if vwap_val is not None and not pd.isna(vwap_val)
                else None
            )
            rows.append({
                "symbol": str(r["symbol"]),
                "date": r["date"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["volume"]),
                "vwap": vwap_clean,
            })
        except (KeyError, TypeError, ValueError):
            logger.debug("Skipping malformed bar record: %s", r, exc_info=True)
            continue
    if not rows:
        return 0
    stmt = sqlite_insert(DailyBar).values(rows)
    update_cols = {c.name: stmt.excluded[c.name] for c in DailyBar.__table__.columns
                   if c.name not in {"symbol", "date"}}
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "date"],
        set_=update_cols,
    )
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(stmt)
            await session.commit()
            return len(rows)
        except Exception:
            await session.rollback()
            logger.warning("DailyBar upsert failed", exc_info=True)
            return 0


async def update_daily_bars(symbols: list[str] | None = None) -> int:
    """Incremental fetch — pull bars since the last stored date for each symbol.

    For initial bootstrap, fetches 5 years of history. Symbols Alpaca
    declines to return are simply skipped (they show up as no rows in
    the response DataFrame).
    """
    if symbols is None:
        symbols = await get_russell_universe()
    today = date.today()
    five_years_ago = today - timedelta(days=5 * 365 + 5)

    last_dates = await _load_last_dates(symbols)

    # Group symbols by their effective start date so we batch fetches.
    starts: dict[date, list[str]] = {}
    for sym in symbols:
        s = last_dates.get(sym, five_years_ago)
        starts.setdefault(s, []).append(sym)

    inserted_total = 0
    for start_date, syms in starts.items():
        fetch_start = start_date + timedelta(days=1)
        if fetch_start >= today:
            continue
        for chunk_start in range(0, len(syms), ALPACA_SYMBOL_CHUNK):
            chunk = syms[chunk_start : chunk_start + ALPACA_SYMBOL_CHUNK]
            try:
                df = await asyncio.to_thread(
                    _fetch_bars_sync, chunk, fetch_start, today
                )
            except Exception:
                logger.warning(
                    "Alpaca fetch failed for %d symbols starting %s",
                    len(chunk),
                    fetch_start,
                    exc_info=True,
                )
                continue
            if df.empty:
                continue
            inserted_total += await _persist_bars(df.to_dict("records"))
    return inserted_total


async def update_active_universe(target_date: date, top_n: int = 100) -> int:
    """Compute and store the top-N active universe for ``target_date``.

    Returns the number of rows written. Returns 0 if no bars exist for
    that date.
    """
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyBar).where(DailyBar.date == target_date)
            )
        ).scalars().all()
        # On weekends / holidays target_date won't have bars yet; fall back
        # to the most recent trading day so the user still sees a universe.
        if not rows:
            most_recent = (
                await session.execute(
                    select(func.max(DailyBar.date)).where(DailyBar.date <= target_date)
                )
            ).scalar()
            if most_recent is None:
                return 0
            target_date = most_recent
            rows = (
                await session.execute(
                    select(DailyBar).where(DailyBar.date == target_date)
                )
            ).scalars().all()
            if not rows:
                return 0

        # If yesterday isn't a trading day (weekend/holiday), fall back to
        # the most recent prior date with bars stored.
        prior_date = (
            await session.execute(
                select(func.max(DailyBar.date)).where(DailyBar.date < target_date)
            )
        ).scalar()
        if prior_date is not None:
            prev_rows = (
                await session.execute(
                    select(DailyBar).where(DailyBar.date == prior_date)
                )
            ).scalars().all()
        else:
            prev_rows = []

        today_df = pd.DataFrame(
            [
                {
                    "symbol": r.symbol,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in rows
            ]
        )
        history_df = pd.DataFrame(
            [{"symbol": r.symbol, "close": r.close} for r in prev_rows]
            if prev_rows
            else [],
            columns=["symbol", "close"],
        )

        scored = compute_activity_score(today_df, history_df)
        scored = (
            scored.sort_values("activity_score", ascending=False)
            .head(top_n)
            .reset_index(drop=True)
        )

        # Wipe and rewrite for this date so re-runs are idempotent.
        await session.execute(
            delete(DailyActiveUniverse).where(
                DailyActiveUniverse.date == target_date
            )
        )
        for rank, row in scored.iterrows():
            session.add(
                DailyActiveUniverse(
                    date=target_date,
                    rank=int(rank) + 1,
                    symbol=str(row["symbol"]),
                    activity_score=float(row["activity_score"]),
                    dollar_volume=float(row["dollar_volume"]),
                    vol_return_score=float(row["vol_return_score"]),
                    range_score=float(row["range_score"]),
                )
            )
        await session.commit()
        return len(scored)


async def get_panel(
    start: date, end: date, symbols: Iterable[str] | None = None
) -> pd.DataFrame:
    """Load OHLCV panel as MultiIndex (date, symbol) DataFrame for [start, end]."""
    async with AsyncSessionLocal() as session:
        query = select(DailyBar).where(DailyBar.date >= start, DailyBar.date <= end)
        if symbols is not None:
            sym_list = list(symbols)
            if not sym_list:
                return pd.DataFrame()
            query = query.where(DailyBar.symbol.in_(sym_list))
        rows = (await session.execute(query)).scalars().all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "symbol": r.symbol,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]
    )
    return df.set_index(["date", "symbol"]).sort_index()


async def get_active_universe(target_date: date, top_n: int = 100) -> list[str]:
    """Return the stored ranking (ascending rank) for ``target_date``."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyActiveUniverse.symbol)
                .where(DailyActiveUniverse.date == target_date)
                .order_by(DailyActiveUniverse.rank)
                .limit(top_n)
            )
        ).scalars().all()
    return list(rows)
