"""Day/week/month trend snapshots from yfinance + live Alpaca quotes."""
from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import alpaca_service
from app.services.monitoring.symbols import _normalize_symbols
from app.services.network_utils import run_sync_with_retries

TREND_CACHE_TTL = timedelta(minutes=20)

_trend_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}


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
