"""Orchestrates fetch + detector dispatch for /api/signals/{symbol}."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.services import chart_service
from core.signals.breakout import detect_breakouts
from core.signals.macd_cross import detect_macd_crosses
from core.signals.rsi_levels import detect_rsi_signals
from core.signals.volume_confirmation import detect_volume_signals


async def compute_for_symbol(symbol: str, *, range_name: str = "3mo") -> dict[str, Any]:
    """Fetch OHLCV bars and run all detectors. Returns dict for SignalsResponse."""
    chart = await chart_service.get_symbol_chart(symbol, range_name=range_name)
    bars = list((chart or {}).get("points") or [])

    signals = []
    for fn in (detect_macd_crosses, detect_rsi_signals,
               detect_volume_signals, detect_breakouts):
        signals.extend(fn(bars))
    signals.sort(key=lambda s: s.ts)

    return {
        "symbol": (chart or {}).get("symbol", symbol),
        "range": (chart or {}).get("range", range_name),
        "interval": (chart or {}).get("interval", ""),
        "signals": [asdict(s) for s in signals],
        "generated_at": datetime.now(timezone.utc),
    }
