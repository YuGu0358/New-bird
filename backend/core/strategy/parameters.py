"""Base parameter model that every strategy extends.

Concrete strategies provide their own subclass with extra fields. The
framework only assumes `universe_symbols` exists since the runner needs to
know which symbols to subscribe to.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrategyParameters(BaseModel):
    """Common parameter surface every strategy must expose.

    Strategies extend this with their own fields (entry/exit thresholds,
    sizing rules, etc.). The framework only relies on `universe_symbols`.
    """

    model_config = ConfigDict(extra="forbid")

    universe_symbols: list[str] = Field(default_factory=list)
