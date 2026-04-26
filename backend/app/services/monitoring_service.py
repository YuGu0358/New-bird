"""Backward-compat shim. New code should import from app.services.monitoring directly."""
from app.services.monitoring import *  # noqa: F401, F403
from app.services.monitoring import (  # noqa: F401
    _build_trend_snapshot,
    _empty_trend_snapshot,
    _normalize_symbol,
    _normalize_symbols,
    _score_candidate,
    _select_reference_price,
    __all__,
)
