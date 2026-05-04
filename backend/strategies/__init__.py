"""Concrete trading strategies. Importing this package registers all of them.

The runner imports `strategies` once at startup so the decorators run before
anyone looks up a strategy by name.
"""
from __future__ import annotations

# Each concrete strategy module triggers @register_strategy on import.
from strategies import strategy_b  # noqa: F401
