"""symbol_info JSON shape for TradingView pine-seeds.

Pine-seeds expects every published ticker to have a sibling ``symbol_info/<TICKER>.json``
file describing how the ticker should appear in TradingView. The structure is
documented in the pine-seeds repo; we produce one entry per Newbird ticker.
"""
from __future__ import annotations

from typing import Literal

SymbolKind = Literal["LEVELS", "VAL", "MACRO"]

_DESCRIPTIONS: dict[str, str] = {
    "LEVELS": "Newbird options walls (call wall, put wall, max pain)",
    "VAL": "Newbird PE channel fair-value bands",
    "MACRO": "Newbird macro ensemble health (ok/warn/danger/neutral counts)",
}


def _full_symbol(ticker: str, kind: str) -> str:
    if kind == "MACRO":
        # Macro feed is global — ignore the per-ticker prefix.
        return "NEWBIRD_MACRO_ENSEMBLE"
    return f"NEWBIRD_{ticker.upper()}_{kind}"


def symbol_info_for(ticker: str, kind: SymbolKind) -> dict:
    """Return the dict serialized to ``symbol_info/<ticker>.json``.

    Shape::

        {
            "symbol":          [<TICKER>],          # list of one because pine-seeds wants a list
            "description":     [<human readable>],
            "currency":        "USD",
            "session-regular": "0930-1600",
            "timezone":        "America/New_York",
            "type":            "indicator"
        }
    """
    if kind not in _DESCRIPTIONS:
        raise ValueError(f"unknown pine-seeds symbol kind: {kind!r}")

    return {
        "symbol": [_full_symbol(ticker, kind)],
        "description": [_DESCRIPTIONS[kind]],
        "currency": "USD",
        "session-regular": "0930-1600",
        "timezone": "America/New_York",
        "type": "indicator",
    }
