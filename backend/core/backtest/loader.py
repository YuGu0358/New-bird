"""Historical bar loader. yfinance is the only source for Phase 3."""
from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import Any

from core.backtest.types import Bar


def _row_to_bar(symbol: str, timestamp: datetime, row: dict[str, Any]) -> Bar | None:
    try:
        open_ = float(row["Open"])
        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])
        volume = float(row.get("Volume", 0.0) or 0.0)
    except (KeyError, TypeError, ValueError):
        return None
    if any(math.isnan(v) for v in (open_, high, low, close)):
        return None
    if close <= 0:
        return None
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _frame_to_bars(symbol: str, frame: Any) -> list[Bar]:
    bars: list[Bar] = []
    previous_close: float | None = None
    for index, row in frame.iterrows():
        timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        row_dict = {key: row[key] for key in row.index}
        bar = _row_to_bar(symbol, timestamp, row_dict)
        if bar is None:
            continue
        if previous_close is not None:
            bar = Bar(
                symbol=bar.symbol,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                previous_close=previous_close,
            )
        bars.append(bar)
        previous_close = bar.close
    return bars


def _download_bars_sync(
    symbols: Sequence[str],
    *,
    start: date,
    end: date,
) -> dict[str, list[Bar]]:
    import yfinance as yf

    if not symbols:
        return {}

    raw = yf.download(
        tickers=list(symbols),
        start=start.isoformat(),
        end=end.isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw is None or getattr(raw, "empty", False):
        return {}

    if getattr(raw.columns, "nlevels", 1) == 1:
        return {symbols[0]: _frame_to_bars(symbols[0], raw)}

    bars_per_symbol: dict[str, list[Bar]] = {}
    top_level = set(raw.columns.get_level_values(0))
    for symbol in symbols:
        if symbol not in top_level:
            continue
        bars_per_symbol[symbol] = _frame_to_bars(symbol, raw[symbol])
    return bars_per_symbol


async def load_daily_bars(
    symbols: Sequence[str],
    *,
    start: date,
    end: date,
) -> dict[str, list[Bar]]:
    """Async wrapper. Runs the blocking yfinance download in a worker thread."""
    return await asyncio.to_thread(_download_bars_sync, symbols, start=start, end=end)
