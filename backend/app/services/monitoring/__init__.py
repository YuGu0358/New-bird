"""Monitoring service package: watchlist + trends + candidate pool + overview.

Public API mirrors the legacy monitoring_service module so all existing
import sites keep working.
"""
from __future__ import annotations

# Public API
from app.services.monitoring.candidates import build_candidate_pool
from app.services.monitoring.overview import get_monitoring_overview
from app.services.monitoring.trends import fetch_trend_snapshots
from app.services.monitoring.watchlist import (
    add_watchlist_symbol,
    ensure_default_watchlist,
    get_alpaca_universe,
    get_selected_symbols,
    remove_watchlist_symbol,
    search_alpaca_universe,
)

# Private helpers used by tests/test_monitoring_service.py and by
# social_signal_service.py. Re-exported so the legacy shim path keeps working.
from app.services.monitoring.candidates import _score_candidate
from app.services.monitoring.symbols import _normalize_symbol, _normalize_symbols
from app.services.monitoring.trends import (
    _build_trend_snapshot,
    _empty_trend_snapshot,
    _select_reference_price,
)

__all__ = [
    "add_watchlist_symbol",
    "build_candidate_pool",
    "ensure_default_watchlist",
    "fetch_trend_snapshots",
    "get_alpaca_universe",
    "get_monitoring_overview",
    "get_selected_symbols",
    "remove_watchlist_symbol",
    "search_alpaca_universe",
]
