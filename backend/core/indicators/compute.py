"""Standard technical-indicator implementations.

Pure compute, no I/O, no third-party dependencies. Each function takes a
list of floats and returns a list of the same length whose first (period − 1)
entries are `None` (warm-up window).

Conventions follow Wilder / J. Murphy / TA-Lib defaults:
- EMA: α = 2 / (period + 1), seed = SMA of the first `period` closes.
- RSI: Wilder's smoothing after the seed. Returns 0..100.
- MACD: EMA(12) − EMA(26); signal = EMA(9) of MACD; histogram = MACD − signal.
- BBANDS: middle = SMA(period); upper = middle + k·σ; σ is sample stdev
  (n−1 denominator, matching TA-Lib's BBANDS default).

These conventions are pinned by tests so a "drive-by improvement" can't
silently change the values returned to existing callers.
"""
from __future__ import annotations

import math
from typing import Iterable


# Catalogue of supported indicators surfaced by the API layer; the value is
# the canonical default `period` (or kwargs in the case of MACD / BBANDS).
INDICATORS: dict[str, dict[str, int | float]] = {
    "sma": {"period": 20},
    "ema": {"period": 20},
    "rsi": {"period": 14},
    "macd": {"fast": 12, "slow": 26, "signal": 9},
    "bbands": {"period": 20, "k": 2.0},
}


def _to_floats(values: Iterable[float]) -> list[float]:
    return [float(v) for v in values]


def sma(values: list[float], period: int) -> list[float | None]:
    """Simple moving average. First (period-1) entries are None."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    rolling_sum = sum(values[:period])
    out[period - 1] = rolling_sum / period
    for i in range(period, len(values)):
        rolling_sum += values[i] - values[i - period]
        out[i] = rolling_sum / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    """Exponential moving average seeded by SMA(period)."""
    if period <= 0:
        raise ValueError("period must be > 0")
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI on closes."""
    if period <= 0:
        raise ValueError("period must be > 0")
    n = len(values)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta > 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, n):
        delta = values[i] - values[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        # Wilder's smoothing (also called modified moving average).
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi_from(avg_gain, avg_loss)
    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        # Pure-rally regime — convention is RSI = 100.
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    values: list[float],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD line, signal line, and histogram.

    Returns (macd_line, signal_line, histogram). Each list is the same
    length as `values` with leading None entries during the warm-up.
    """
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("fast, slow, signal must all be > 0")
    if fast >= slow:
        raise ValueError("fast must be < slow")
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    macd_line: list[float | None] = []
    for f, s in zip(fast_ema, slow_ema):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(f - s)

    # Signal is EMA(signal) of the MACD line itself, but we can only feed
    # it the non-None tail. Pad with None for the warm-up of the slow EMA.
    macd_tail = [v for v in macd_line if v is not None]
    signal_tail = ema(macd_tail, signal) if macd_tail else []
    pad_len = len(macd_line) - len(signal_tail)
    signal_line: list[float | None] = [None] * pad_len + list(signal_tail)

    histogram: list[float | None] = []
    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)
    return macd_line, signal_line, histogram


def bbands(
    values: list[float],
    *,
    period: int = 20,
    k: float = 2.0,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Bollinger Bands (upper, middle, lower)."""
    if period <= 1:
        raise ValueError("period must be > 1")
    if k <= 0:
        raise ValueError("k must be > 0")
    middle = sma(values, period)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        mean = sum(window) / period
        var = sum((v - mean) ** 2 for v in window) / (period - 1)  # sample stdev
        sd = math.sqrt(var)
        upper[i] = mean + k * sd
        lower[i] = mean - k * sd
    return upper, middle, lower


def compute_indicator(
    name: str,
    closes: list[float],
    *,
    params: dict[str, int | float] | None = None,
) -> dict[str, list[float | None]]:
    """Dispatch helper used by the service layer.

    Returns a dict mapping series-name → values. Single-line indicators
    produce {"value": [...]}; MACD produces {"macd", "signal", "histogram"};
    BBANDS produces {"upper", "middle", "lower"}.
    """
    if name not in INDICATORS:
        raise ValueError(
            f"Unknown indicator {name!r}. Supported: {sorted(INDICATORS)}"
        )
    closes = _to_floats(closes)
    params = dict(INDICATORS[name]) | dict(params or {})

    if name == "sma":
        return {"value": sma(closes, int(params["period"]))}
    if name == "ema":
        return {"value": ema(closes, int(params["period"]))}
    if name == "rsi":
        return {"value": rsi(closes, int(params["period"]))}
    if name == "macd":
        m, s, h = macd(
            closes,
            fast=int(params["fast"]),
            slow=int(params["slow"]),
            signal=int(params["signal"]),
        )
        return {"macd": m, "signal": s, "histogram": h}
    if name == "bbands":
        u, m, l = bbands(
            closes,
            period=int(params["period"]),
            k=float(params["k"]),
        )
        return {"upper": u, "middle": m, "lower": l}
    # Unreachable — INDICATORS gate covers every branch above.
    raise ValueError(f"Unknown indicator {name!r}")
