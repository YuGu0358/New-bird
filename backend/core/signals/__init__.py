"""Pure technical-signal detectors.

Each detector takes a list of OHLCV bar dicts (the shape returned by
chart_service.get_symbol_chart's `points` field) and returns a list of
Signal events. No I/O, no global state — fully testable in isolation.
"""
from core.signals.rsi_divergence import detect_rsi_divergences
from core.signals.types import Signal, SignalDirection, SignalKind

__all__ = ["Signal", "SignalDirection", "SignalKind", "detect_rsi_divergences"]
