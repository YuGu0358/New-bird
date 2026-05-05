"""Daily fundamentals refresh — Polygon Reference + Financials API.

Pulls per-symbol financial statement data and writes a daily snapshot
to ``factor_daily_fundamentals``. Quarterly statements (income / balance
sheet / cash flow) are forward-filled into daily rows: a metric reported
on filing date Y is the assumption for every date ≥ Y until the next
filing supersedes it. Daily-snapshot fields (market_cap, share count)
are written from the reference-tickers endpoint.

Two endpoints used (both work on the existing Polygon plan):

- ``GET /v3/reference/tickers/{symbol}`` — current snapshot: market_cap,
  shares_outstanding.
- ``GET /vX/reference/financials?ticker=X`` — quarterly financials with
  filing_date / fiscal_period; nested ``financials`` dict has
  balance_sheet / income_statement / cash_flow_statement / comprehensive_income.

Computed metrics:
  - ``pe_ratio``     = market_cap / net_income_ttm
  - ``pb_ratio``     = market_cap / book_value
  - ``eps_ttm``      = net_income_ttm / shares_outstanding
  - ``gross_margin`` = gross_profit_ttm / revenue_ttm
  - ``debt_to_equity`` = total_debt / book_value
  - ``roe``          = net_income_ttm / book_value
  - ``revenue_ttm``  = sum of last 4 quarterly revenue rows

short_interest_pct is left NULL for now — Polygon's free tier doesn't
include the short-interest endpoint; will fill in Phase 3.4 via yfinance.

Refresh cadence: daily, after market close, alongside the bar refresh.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app import runtime_settings
from app.db.engine import AsyncSessionLocal
from app.db.tables import FactorDailyFundamentals

logger = logging.getLogger(__name__)


_POLYGON_BASE = "https://api.polygon.io"
_HTTP_TIMEOUT = 15.0
_RPS_DELAY = 0.25  # respect Polygon free-tier rate limit (~5 RPS)
_BATCH_BAR = 500  # chunk size for INSERT/UPSERT — same SQLite cap as DailyBar


def _api_key() -> str:
    key = runtime_settings.get_setting("POLYGON_API_KEY", "") or ""
    if not key:
        raise RuntimeError("POLYGON_API_KEY missing")
    return key


async def _get_json(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    p = dict(params or {})
    p["apiKey"] = _api_key()
    r = await client.get(f"{_POLYGON_BASE}{path}", params=p, timeout=_HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _safe(d: dict[str, Any] | None, *keys: str) -> float | None:
    """Walk a nested dict, returning the leaf .value (Polygon financials
    items are wrapped in {"value": float, "unit": str}). Returns None on
    any miss."""
    if not d:
        return None
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    if isinstance(cur, dict):
        cur = cur.get("value")
    if cur is None:
        return None
    try:
        return float(cur)
    except (TypeError, ValueError):
        return None


def _ttm_sum(quarters: list[dict[str, Any]], *path: str) -> float | None:
    """Sum a metric across the last 4 quarterly statements."""
    vals: list[float] = []
    for q in quarters[:4]:
        v = _safe(q.get("financials") or {}, *path)
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    return float(sum(vals))


async def _fetch_snapshot_blocking(client: httpx.AsyncClient, symbol: str) -> dict[str, Any]:
    """One call per symbol — current market cap + shares outstanding."""
    try:
        data = await _get_json(client, f"/v3/reference/tickers/{symbol}")
    except Exception as exc:  # noqa: BLE001
        logger.debug("polygon snapshot failed for %s: %s", symbol, exc)
        return {}
    r = data.get("results") or {}
    return {
        "market_cap": r.get("market_cap"),
        "shares_outstanding": (
            r.get("share_class_shares_outstanding")
            or r.get("weighted_shares_outstanding")
        ),
    }


async def _fetch_financials_blocking(
    client: httpx.AsyncClient, symbol: str, *, lookback_quarters: int = 5
) -> list[dict[str, Any]]:
    """Last ``lookback_quarters`` quarterly statements, newest first."""
    try:
        data = await _get_json(
            client,
            "/vX/reference/financials",
            params={
                "ticker": symbol,
                "limit": lookback_quarters,
                "timeframe": "quarterly",
                "order": "desc",
                "sort": "filing_date",
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("polygon financials failed for %s: %s", symbol, exc)
        return []
    return list(data.get("results") or [])


def _compute_per_symbol(
    snapshot: dict[str, Any], quarters: list[dict[str, Any]]
) -> dict[str, float | None]:
    """Combine snapshot + last-4Q financials into derived metrics."""
    market_cap = snapshot.get("market_cap")
    shares = snapshot.get("shares_outstanding")

    revenue_ttm = _ttm_sum(quarters, "income_statement", "revenues")
    gross_profit_ttm = _ttm_sum(quarters, "income_statement", "gross_profit")
    net_income_ttm = _ttm_sum(quarters, "income_statement", "net_income_loss")

    book_value = None
    total_debt = None
    if quarters:
        latest_bs = (quarters[0].get("financials") or {}).get("balance_sheet") or {}
        book_value = _safe(latest_bs, "equity")
        total_debt = (
            _safe(latest_bs, "long_term_debt")
            or _safe(latest_bs, "noncurrent_liabilities")
        )

    pe_ratio = (
        float(market_cap) / float(net_income_ttm)
        if market_cap and net_income_ttm and net_income_ttm > 0
        else None
    )
    pb_ratio = (
        float(market_cap) / float(book_value)
        if market_cap and book_value and book_value > 0
        else None
    )
    eps_ttm = (
        float(net_income_ttm) / float(shares)
        if net_income_ttm and shares and shares > 0
        else None
    )
    gross_margin = (
        float(gross_profit_ttm) / float(revenue_ttm)
        if gross_profit_ttm and revenue_ttm and revenue_ttm > 0
        else None
    )
    debt_to_equity = (
        float(total_debt) / float(book_value)
        if total_debt and book_value and book_value > 0
        else None
    )
    roe = (
        float(net_income_ttm) / float(book_value)
        if net_income_ttm and book_value and book_value > 0
        else None
    )

    return {
        "market_cap": float(market_cap) if market_cap else None,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "eps_ttm": eps_ttm,
        "revenue_ttm": revenue_ttm,
        "gross_margin": gross_margin,
        "debt_to_equity": debt_to_equity,
        "roe": roe,
    }


async def refresh_fundamentals(
    symbols: list[str], *, target_date: date | None = None
) -> int:
    """Refresh and persist fundamentals for ``symbols`` on ``target_date``
    (defaults to today). Returns the number of rows written.

    Per-symbol I/O is sequential to respect Polygon's rate limit; per
    fetch latency ≈ 0.5s, so 100 symbols ≈ 1 minute total.
    """
    if not symbols:
        return 0
    target = target_date or datetime.now(timezone.utc).date()
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for sym in symbols:
            snap = await _fetch_snapshot_blocking(client, sym)
            await asyncio.sleep(_RPS_DELAY)
            quarters = await _fetch_financials_blocking(client, sym)
            await asyncio.sleep(_RPS_DELAY)
            metrics = _compute_per_symbol(snap, quarters)
            row = {
                "symbol": sym,
                "date": target,
                "refreshed_at": datetime.now(timezone.utc),
                "short_interest_pct": None,
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
