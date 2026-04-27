"""Macro environment engine — FRED indicators + threshold-based signal levels.

Layout mirrors `core/agents/` and `core/quantlib/`: pure-python algorithms with
no FastAPI/HTTP/DB knowledge. The thin app-layer adapter
(`app/services/macro_service.py`) is what the router talks to.

Borrowed in spirit from Tradewell's Sprint 3 macro module — we keep the
threshold spec, the indicator seed list, and the FRED client minimal.
"""
from __future__ import annotations

from core.macro.fred import (
    FREDClient,
    FREDConfigError,
    FREDObservation,
)
from core.macro.indicators_seed import SEED_INDICATORS, IndicatorSeed
from core.macro.signals import SignalLevel, evaluate_signal

__all__ = [
    "FREDClient",
    "FREDConfigError",
    "FREDObservation",
    "SEED_INDICATORS",
    "IndicatorSeed",
    "SignalLevel",
    "evaluate_signal",
]
