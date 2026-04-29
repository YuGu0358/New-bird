from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.network_utils import run_sync_with_retries

# Range → (yfinance period, yfinance interval, cache TTL).
# yfinance limits: 1m bars max ~7d back, ≤30m bars max ~60d back, daily+ has
# no such cap. We pick the finest interval each range allows so the chart
# shows per-minute resolution where possible. TTL scales with bar size — a
# 1-minute view stales fast; a yearly view doesn't.
_CHART_RANGE_CONFIG: dict[str, dict[str, Any]] = {
    "1d":  {"period": "1d",  "interval": "1m",  "ttl": timedelta(seconds=60)},
    "5d":  {"period": "5d",  "interval": "5m",  "ttl": timedelta(minutes=2)},
    "1mo": {"period": "1mo", "interval": "1h",  "ttl": timedelta(minutes=5)},
    "3mo": {"period": "3mo", "interval": "1d",  "ttl": timedelta(minutes=10)},
    "6mo": {"period": "6mo", "interval": "1d",  "ttl": timedelta(minutes=10)},
    "1y":  {"period": "1y",  "interval": "1d",  "ttl": timedelta(minutes=30)},
    "2y":  {"period": "2y",  "interval": "1wk", "ttl": timedelta(minutes=30)},
}
_chart_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_range(value: str | None) -> str:
    normalized = str(value or "3mo").strip().lower()
    if normalized not in _CHART_RANGE_CONFIG:
        raise ValueError("不支持的走势图区间。")
    return normalized


def _download_chart_frame_sync(symbol: str, period: str, interval: str):
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    frame = ticker.history(
        period=period,
        interval=interval,
        auto_adjust=False,
        prepost=False,
    )
    return frame


def _frame_to_points(frame) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", False):
        return []

    points: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        def _to_float(key: str) -> float:
            try:
                return float(row.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        volume_value = row.get("Volume", 0)
        try:
            volume = int(volume_value or 0)
        except (TypeError, ValueError):
            volume = 0

        points.append(
            {
                "timestamp": timestamp,
                "open": _to_float("Open"),
                "high": _to_float("High"),
                "low": _to_float("Low"),
                "close": _to_float("Close"),
                "volume": max(volume, 0),
            }
        )

    return [point for point in points if point["close"] > 0]


def _compute_range_change_percent(points: list[dict[str, Any]]) -> float | None:
    if len(points) < 2:
        return None
    start_close = float(points[0]["close"])
    end_close = float(points[-1]["close"])
    if start_close <= 0:
        return None
    return round(((end_close - start_close) / start_close) * 100, 2)


async def get_symbol_chart(symbol: str, range_name: str = "3mo") -> dict[str, Any]:
    """Return historical chart points for a symbol using yfinance."""

    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        raise ValueError("股票代码不能为空。")

    normalized_range = _normalize_range(range_name)
    cache_key = (normalized_symbol, normalized_range)
    now = datetime.now(timezone.utc)

    range_config = _CHART_RANGE_CONFIG[normalized_range]
    ttl: timedelta = range_config["ttl"]
    cached_item = _chart_cache.get(cache_key)
    if cached_item is not None and now - cached_item[0] <= ttl:
        return cached_item[1]

    frame = await run_sync_with_retries(
        _download_chart_frame_sync,
        normalized_symbol,
        range_config["period"],
        range_config["interval"],
    )
    points = _frame_to_points(frame)
    if not points:
        raise ValueError(f"{normalized_symbol} 当前没有可用走势图数据。")

    payload = {
        "symbol": normalized_symbol,
        "range": normalized_range,
        "interval": range_config["interval"],
        "generated_at": now,
        "latest_price": points[-1]["close"],
        "range_change_percent": _compute_range_change_percent(points),
        "points": points,
    }
    _chart_cache[cache_key] = (now, payload)
    return payload
