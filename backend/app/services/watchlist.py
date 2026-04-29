"""Single source of truth for the platform watchlist.

`PINE_SEEDS_WATCHLIST` is the canonical setting key — it was originally
named for the TradingView pine-seeds export but has grown into the
"which symbols does this app care about?" knob. Multiple periodic jobs
read it: options_chain_sync, polygon_ws_publisher, future portfolio
heatmap. Centralizing the parse here keeps:

- The default list ("SPY,QQQ,NVDA,AAPL") in ONE place — runtime_settings.py
  defines the SettingDefinition, get_setting() returns its default when
  unset, and this module wraps the parse so callers don't reimplement
  comma-split + strip + uppercase.
- The split semantics consistent: split on commas, strip whitespace,
  drop empties, uppercase.
"""
from __future__ import annotations

from app import runtime_settings


def get_watchlist() -> list[str]:
    """Return the configured watchlist as an uppercase symbol list.

    Falls through to the SettingDefinition's default when the user
    hasn't customized the setting (runtime_settings.get_setting handles
    that fallback automatically).
    """
    raw = runtime_settings.get_setting("PINE_SEEDS_WATCHLIST") or ""
    return [s.strip().upper() for s in raw.split(",") if s.strip()]
