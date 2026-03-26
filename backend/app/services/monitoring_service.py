from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import CandidatePoolItem, WatchlistSymbol
from app.services import alpaca_service, openai_service, tavily_service
from app.services.network_utils import run_sync_with_retries

DEFAULT_SELECTED_SYMBOLS = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "TSLA",
    "JPM",
    "V",
    "MA",
    "UNH",
    "HD",
    "PG",
    "XOM",
    "KO",
    "PEP",
    "DIS",
    "CRM",
    "NFLX",
    "COST",
]

TECH_CANDIDATE_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "AVGO",
    "AMD",
    "ADBE",
    "CRM",
    "ORCL",
    "NOW",
    "SNOW",
    "PANW",
    "CRWD",
    "PLTR",
    "MDB",
    "QCOM",
    "INTU",
    "SMCI",
]

ETF_CANDIDATE_SYMBOLS = [
    "QQQ",
    "SPY",
    "VOO",
    "IVV",
    "VTI",
    "XLK",
    "VGT",
    "SMH",
    "SOXX",
    "IGV",
    "DIA",
    "IWM",
]

TREND_CACHE_TTL = timedelta(minutes=20)
UNIVERSE_CACHE_TTL = timedelta(hours=12)
MAX_CANDIDATES = 5

_trend_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}
_universe_cache: dict[str, Any] = {"fetched_at": None, "items": []}


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for symbol in symbols:
        normalized_symbol = _normalize_symbol(symbol)
        if not normalized_symbol or normalized_symbol in seen:
            continue
        seen.add(normalized_symbol)
        normalized.append(normalized_symbol)

    return normalized


def _empty_trend_snapshot(symbol: str, as_of: datetime) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "as_of": as_of,
        "current_price": None,
        "previous_day_price": None,
        "previous_week_price": None,
        "previous_month_price": None,
        "day_change_percent": None,
        "week_change_percent": None,
        "month_change_percent": None,
        "day_direction": "flat",
        "week_direction": "flat",
        "month_direction": "flat",
    }


def _direction(percent_change: float | None) -> str:
    if percent_change is None:
        return "flat"
    if percent_change > 0:
        return "up"
    if percent_change < 0:
        return "down"
    return "flat"


def _percent_change(current_price: float | None, reference_price: float | None) -> float | None:
    if current_price in (None, 0) or reference_price in (None, 0):
        return None
    return ((current_price - reference_price) / reference_price) * 100


def _select_reference_price(
    points: Sequence[tuple[datetime, float]],
    *,
    lookback_days: int,
    fallback_index: int,
) -> float | None:
    if not points:
        return None

    latest_timestamp = points[-1][0]
    target_time = latest_timestamp - timedelta(days=lookback_days)

    for timestamp, price in reversed(points[:-1]):
        if timestamp <= target_time:
            return price

    if len(points) > fallback_index:
        return points[-(fallback_index + 1)][1]

    if len(points) > 1:
        return points[0][1]

    return None


def _build_trend_snapshot(
    symbol: str,
    history_points: Sequence[tuple[datetime, float]],
    live_snapshot: dict[str, Any] | None,
    as_of: datetime,
) -> dict[str, Any]:
    if not history_points and not live_snapshot:
        return _empty_trend_snapshot(symbol, as_of)

    last_close = history_points[-1][1] if history_points else None
    current_price = None
    if isinstance(live_snapshot, dict):
        live_price = live_snapshot.get("price")
        if isinstance(live_price, (int, float)) and live_price > 0:
            current_price = float(live_price)

    current_price = current_price or last_close
    previous_day_price = None
    if isinstance(live_snapshot, dict):
        live_previous_close = live_snapshot.get("previous_close")
        if isinstance(live_previous_close, (int, float)) and live_previous_close > 0:
            previous_day_price = float(live_previous_close)

    if previous_day_price is None:
        previous_day_price = _select_reference_price(
            history_points,
            lookback_days=1,
            fallback_index=1,
        )

    previous_week_price = _select_reference_price(
        history_points,
        lookback_days=7,
        fallback_index=5,
    )
    previous_month_price = _select_reference_price(
        history_points,
        lookback_days=30,
        fallback_index=21,
    )

    day_change_percent = _percent_change(current_price, previous_day_price)
    week_change_percent = _percent_change(current_price, previous_week_price)
    month_change_percent = _percent_change(current_price, previous_month_price)

    return {
        "symbol": symbol,
        "as_of": as_of,
        "current_price": current_price,
        "previous_day_price": previous_day_price,
        "previous_week_price": previous_week_price,
        "previous_month_price": previous_month_price,
        "day_change_percent": day_change_percent,
        "week_change_percent": week_change_percent,
        "month_change_percent": month_change_percent,
        "day_direction": _direction(day_change_percent),
        "week_direction": _direction(week_change_percent),
        "month_direction": _direction(month_change_percent),
    }


def _score_candidate(trend: dict[str, Any]) -> float | None:
    day = trend.get("day_change_percent")
    week = trend.get("week_change_percent")
    month = trend.get("month_change_percent")

    if not isinstance(day, (int, float)) or not isinstance(week, (int, float)) or not isinstance(month, (int, float)):
        return None

    score = (day * 0.2) + (week * 0.35) + (month * 0.45)
    return round(score, 4)


def _fallback_candidate_reason(symbol: str, trend: dict[str, Any]) -> str:
    week = trend.get("week_change_percent")
    month = trend.get("month_change_percent")
    week_text = f"近一周 {week:.2f}%" if isinstance(week, (int, float)) else "近一周数据缺失"
    month_text = f"近一月 {month:.2f}%" if isinstance(month, (int, float)) else "近一月数据缺失"
    return f"{symbol} 在科技/ETF 候选池中动量靠前，{week_text}，{month_text}。"


def _compress_reason(summary: str, fallback: str) -> str:
    compact_summary = " ".join(summary.split())
    if not compact_summary:
        return fallback
    if len(compact_summary) <= 180:
        return compact_summary
    return f"{compact_summary[:177].rstrip()}..."


def _history_frame_to_points(frame: Any) -> list[tuple[datetime, float]]:
    close_series = None
    if hasattr(frame, "get"):
        close_series = frame.get("Close")

    if close_series is None:
        return []

    points: list[tuple[datetime, float]] = []
    for index, close_price in close_series.items():
        if close_price is None:
            continue
        try:
            numeric_close = float(close_price)
        except (TypeError, ValueError):
            continue

        if math.isnan(numeric_close) or numeric_close <= 0:
            continue

        timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        points.append((timestamp, numeric_close))

    return points


def _download_histories_sync(symbols: Sequence[str]) -> dict[str, list[tuple[datetime, float]]]:
    import yfinance as yf

    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        return {}

    raw_data = yf.download(
        tickers=normalized_symbols,
        period="3mo",
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )

    if raw_data is None or getattr(raw_data, "empty", False):
        return {}

    if getattr(raw_data.columns, "nlevels", 1) == 1:
        return {normalized_symbols[0]: _history_frame_to_points(raw_data)}

    histories: dict[str, list[tuple[datetime, float]]] = {}
    top_level = set(raw_data.columns.get_level_values(0))
    for symbol in normalized_symbols:
        if symbol not in top_level:
            continue
        histories[symbol] = _history_frame_to_points(raw_data[symbol])

    return histories


async def ensure_default_watchlist(session: AsyncSession) -> None:
    """Seed the default watchlist for first-time project startup."""

    result = await session.execute(select(WatchlistSymbol.id).limit(1))
    if result.first() is not None:
        return

    for symbol in DEFAULT_SELECTED_SYMBOLS:
        session.add(WatchlistSymbol(symbol=symbol))

    await session.commit()


async def get_selected_symbols(session: AsyncSession) -> list[str]:
    result = await session.execute(
        select(WatchlistSymbol).order_by(WatchlistSymbol.created_at, WatchlistSymbol.symbol)
    )
    return [row.symbol for row in result.scalars().all()]


async def add_watchlist_symbol(session: AsyncSession, symbol: str) -> list[str]:
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        raise ValueError("股票代码不能为空。")

    result = await session.execute(
        select(WatchlistSymbol).where(WatchlistSymbol.symbol == normalized_symbol)
    )
    existing = result.scalars().first()
    if existing is None:
        session.add(WatchlistSymbol(symbol=normalized_symbol))
        await session.commit()

    return await get_selected_symbols(session)


async def remove_watchlist_symbol(session: AsyncSession, symbol: str) -> list[str]:
    normalized_symbol = _normalize_symbol(symbol)
    await session.execute(delete(WatchlistSymbol).where(WatchlistSymbol.symbol == normalized_symbol))
    await session.commit()
    return await get_selected_symbols(session)


async def get_alpaca_universe(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    cached_at = _universe_cache.get("fetched_at")
    cached_items = _universe_cache.get("items") or []

    if (
        not force_refresh
        and isinstance(cached_at, datetime)
        and now - cached_at <= UNIVERSE_CACHE_TTL
        and cached_items
    ):
        return list(cached_items)

    assets = await alpaca_service.list_assets(status="active", asset_class="us_equity")
    normalized_assets = sorted(
        (
            asset
            for asset in assets
            if asset.get("tradable") and asset.get("symbol")
        ),
        key=lambda asset: str(asset.get("symbol", "")),
    )
    _universe_cache["fetched_at"] = now
    _universe_cache["items"] = normalized_assets
    return list(normalized_assets)


async def search_alpaca_universe(query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    assets = await get_alpaca_universe()
    normalized_query = query.strip().upper()

    if normalized_query:
        filtered = [
            asset
            for asset in assets
            if normalized_query in str(asset.get("symbol", "")).upper()
            or normalized_query in str(asset.get("name", "")).upper()
        ]
        filtered.sort(
            key=lambda asset: (
                str(asset.get("symbol", "")).upper() != normalized_query,
                not str(asset.get("symbol", "")).upper().startswith(normalized_query),
                normalized_query not in str(asset.get("symbol", "")).upper(),
                normalized_query not in str(asset.get("name", "")).upper(),
                str(asset.get("symbol", "")).upper(),
            )
        )
    else:
        filtered = assets

    return filtered[: max(1, min(limit, 200))]


async def fetch_trend_snapshots(
    symbols: Sequence[str],
    *,
    force_refresh: bool = False,
) -> dict[str, dict[str, Any]]:
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        return {}

    now = datetime.now(timezone.utc)
    stale_symbols = [
        symbol
        for symbol in normalized_symbols
        if force_refresh
        or symbol not in _trend_cache
        or now - _trend_cache[symbol][0] > TREND_CACHE_TTL
    ]

    if stale_symbols:
        try:
            live_snapshots = await alpaca_service.get_market_snapshots(stale_symbols)
        except Exception:
            live_snapshots = {}

        try:
            histories = await run_sync_with_retries(_download_histories_sync, stale_symbols)
        except Exception:
            histories = {}

        for symbol in stale_symbols:
            snapshot = _build_trend_snapshot(
                symbol,
                histories.get(symbol, []),
                live_snapshots.get(symbol),
                now,
            )
            _trend_cache[symbol] = (now, snapshot)

    return {
        symbol: _trend_cache[symbol][1]
        for symbol in normalized_symbols
        if symbol in _trend_cache
    }


async def _build_candidate_reasons(
    picked: Sequence[dict[str, Any]],
) -> dict[str, str]:
    async def _load_reason(item: dict[str, Any]) -> tuple[str, str]:
        symbol = str(item["symbol"])
        fallback_reason = _fallback_candidate_reason(symbol, item["trend"])

        try:
            response = await tavily_service.fetch_news_summary(symbol)
            summary = str(response.get("summary", "")).strip()
        except Exception:
            summary = ""

        return symbol, _compress_reason(summary, fallback_reason)

    responses = await asyncio.gather(*[_load_reason(item) for item in picked], return_exceptions=False)
    return {symbol: reason for symbol, reason in responses}


def _pick_top_candidates(scored_items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_items = sorted(
        scored_items,
        key=lambda item: (float(item["score"]), float(item["trend"].get("month_change_percent") or 0.0)),
        reverse=True,
    )

    tech_items = [item for item in sorted_items if item["category"] == "科技股"]
    etf_items = [item for item in sorted_items if item["category"] == "ETF"]

    picked: list[dict[str, Any]] = []
    picked.extend(tech_items[:3])
    picked.extend(etf_items[:2])

    picked_symbols = {item["symbol"] for item in picked}
    for item in sorted_items:
        if len(picked) >= MAX_CANDIDATES:
            break
        if item["symbol"] in picked_symbols:
            continue
        picked.append(item)
        picked_symbols.add(item["symbol"])

    return picked[:MAX_CANDIDATES]


async def _load_cached_candidate_pool(
    session: AsyncSession,
    snapshot_date: str,
) -> list[CandidatePoolItem]:
    result = await session.execute(
        select(CandidatePoolItem)
        .where(CandidatePoolItem.snapshot_date == snapshot_date)
        .order_by(CandidatePoolItem.rank, CandidatePoolItem.symbol)
    )
    return result.scalars().all()


async def build_candidate_pool(
    session: AsyncSession,
    *,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Create or load today's top-5 candidate pool."""

    snapshot_date = datetime.now(timezone.utc).date().isoformat()

    if not force_refresh:
        cached_rows = await _load_cached_candidate_pool(session, snapshot_date)
        if cached_rows:
            trend_map = await fetch_trend_snapshots([row.symbol for row in cached_rows])
            now = datetime.now(timezone.utc)
            return [
                {
                    "symbol": row.symbol,
                    "rank": row.rank,
                    "category": row.category,
                    "score": row.score,
                    "reason": row.reason,
                    "trend": trend_map.get(row.symbol, _empty_trend_snapshot(row.symbol, now)),
                }
                for row in cached_rows
            ]

    candidate_symbols = _normalize_symbols(TECH_CANDIDATE_SYMBOLS + ETF_CANDIDATE_SYMBOLS)
    trend_map = await fetch_trend_snapshots(candidate_symbols, force_refresh=True)

    scored_items: list[dict[str, Any]] = []
    for symbol in candidate_symbols:
        trend = trend_map.get(symbol)
        if trend is None:
            continue
        score = _score_candidate(trend)
        if score is None:
            continue
        scored_items.append(
            {
                "symbol": symbol,
                "category": "ETF" if symbol in ETF_CANDIDATE_SYMBOLS else "科技股",
                "score": score,
                "trend": trend,
            }
        )

    deterministic_picks = _pick_top_candidates(scored_items)
    shortlist = sorted(
        scored_items,
        key=lambda item: float(item["score"]),
        reverse=True,
    )[:8]

    picked = deterministic_picks
    if openai_service.is_configured() and shortlist:
        try:
            ai_ranked = await openai_service.rank_candidates(shortlist)
            if len(ai_ranked) >= MAX_CANDIDATES:
                picked = ai_ranked
        except Exception:
            picked = deterministic_picks

    needs_reason_refresh = any(not item.get("reason") for item in picked)
    if needs_reason_refresh:
        reasons = await _build_candidate_reasons(picked)
    else:
        reasons = {str(item["symbol"]).upper(): str(item.get("reason", "")).strip() for item in picked}

    await session.execute(delete(CandidatePoolItem).where(CandidatePoolItem.snapshot_date == snapshot_date))
    for index, item in enumerate(picked, start=1):
        session.add(
            CandidatePoolItem(
                snapshot_date=snapshot_date,
                symbol=item["symbol"],
                rank=index,
                category=item["category"],
                score=float(item["score"]),
                reason=reasons.get(item["symbol"], _fallback_candidate_reason(item["symbol"], item["trend"])),
            )
        )

    await session.commit()

    return [
        {
            "symbol": item["symbol"],
            "rank": index,
            "category": item["category"],
            "score": float(item["score"]),
            "reason": reasons.get(item["symbol"], _fallback_candidate_reason(item["symbol"], item["trend"])),
            "trend": item["trend"],
        }
        for index, item in enumerate(picked, start=1)
    ]


async def get_monitoring_overview(
    session: AsyncSession,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return the monitoring dashboard payload without altering trade logic."""

    await ensure_default_watchlist(session)

    selected_symbols = await get_selected_symbols(session)

    try:
        positions = await alpaca_service.list_positions()
    except Exception:
        positions = []

    position_symbols = [str(item.get("symbol", "")).upper() for item in positions if item.get("symbol")]
    candidate_pool = await build_candidate_pool(session, force_refresh=force_refresh)
    candidate_symbols = [str(item["symbol"]).upper() for item in candidate_pool]

    tracked_symbols = _normalize_symbols(selected_symbols + candidate_symbols + position_symbols)
    trend_map = await fetch_trend_snapshots(tracked_symbols, force_refresh=force_refresh)

    candidate_pool_payload = []
    now = datetime.now(timezone.utc)
    for item in candidate_pool:
        candidate_pool_payload.append(
            {
                "symbol": item["symbol"],
                "rank": item["rank"],
                "category": item["category"],
                "score": item["score"],
                "reason": item["reason"],
                "trend": trend_map.get(item["symbol"], _empty_trend_snapshot(item["symbol"], now)),
            }
        )

    tracked_payload = []
    candidate_set = set(candidate_symbols)
    selected_set = set(selected_symbols)
    position_set = set(position_symbols)

    for symbol in tracked_symbols:
        tags: list[str] = []
        if symbol in selected_set:
            tags.append("自选")
        if symbol in candidate_set:
            tags.append("候选")
        if symbol in position_set:
            tags.append("持仓")

        tracked_payload.append(
            {
                "symbol": symbol,
                "tags": tags,
                "trend": trend_map.get(symbol, _empty_trend_snapshot(symbol, now)),
            }
        )

    try:
        universe_asset_count = len(await get_alpaca_universe())
    except Exception:
        universe_asset_count = 0

    return {
        "generated_at": datetime.now(timezone.utc),
        "universe_asset_count": universe_asset_count,
        "selected_symbols": selected_symbols,
        "candidate_pool": candidate_pool_payload,
        "tracked_symbols": tracked_payload,
    }
