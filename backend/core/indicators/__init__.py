"""Pure-Python technical indicators (SMA / EMA / RSI / MACD / BBANDS).

Standalone implementations to avoid a system dependency on TA-Lib (which
needs a compiled C library and is painful to install on macOS / Windows
arm64). Test suite pins exact reference values so behaviour stays stable.
"""
from core.indicators.compute import (
    INDICATORS,
    bbands,
    compute_indicator,
    ema,
    macd,
    rsi,
    sma,
)

__all__ = [
    "INDICATORS",
    "bbands",
    "compute_indicator",
    "ema",
    "macd",
    "rsi",
    "sma",
]
