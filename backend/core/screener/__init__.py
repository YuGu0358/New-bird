"""Multi-asset screener — fixed universe + pure compute helpers.

The service layer (`app/services/screener_service`) handles the yfinance
fetch and 1-hour cache. This package owns:

- `universe`: the frozen 55-name universe (5 names per GICS sector × 11).
- `compute`: pure filter / sort / paginate helpers over enriched rows.
"""
from core.screener.universe import SCREENER_UNIVERSE, ScreenerUniverseEntry
from core.screener.compute import (
    SORTABLE_COLUMNS,
    ScreenerFilter,
    ScreenerRow,
    apply_filter,
    sort_and_paginate,
)

__all__ = [
    "SCREENER_UNIVERSE",
    "SORTABLE_COLUMNS",
    "ScreenerFilter",
    "ScreenerRow",
    "ScreenerUniverseEntry",
    "apply_filter",
    "sort_and_paginate",
]
