"""Strategy ABC — the interface every concrete strategy must implement.

Lifecycle (driven by the runner):

    strategy = StrategyClass(parameters)
    await strategy.on_start(ctx)
    while running:
        if periodic_sync_due:
            await strategy.on_periodic_sync(ctx, now)
        for tick in incoming_quotes:
            await strategy.on_tick(ctx, tick)
    await strategy.on_stop(ctx)

Strategies do NOT submit orders directly in Phase 2 — they mutate their own
in-memory state and call broker functions internally (preserving Strategy B's
current behavior). Phase 4 introduces an OrderIntent return type and a Broker
shim on the context, completing the abstraction.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.models import StrategyExecutionParameters

from core.strategy.context import StrategyContext


class Strategy(ABC):
    """Abstract base for all trading strategies."""

    #: Stable identifier used by registry and DB. Concrete classes override.
    name: str = ""

    #: One-line human-readable description shown in admin UI.
    description: str = ""

    @classmethod
    @abstractmethod
    def parameters_schema(cls) -> type[StrategyExecutionParameters]:
        """Return the Pydantic model class describing this strategy's params.

        Used by the API to surface a parameter schema to the frontend, and by
        the profile service to validate user-supplied params before saving.
        """

    def __init__(self, parameters: StrategyExecutionParameters) -> None:
        self.parameters = parameters

    @abstractmethod
    def universe(self) -> list[str]:
        """Symbols the runner should subscribe to for this strategy."""

    @abstractmethod
    async def on_start(self, ctx: StrategyContext) -> None:
        """One-time setup (hydrate state from broker, etc.)."""

    @abstractmethod
    async def on_periodic_sync(self, ctx: StrategyContext, now: datetime) -> None:
        """Periodic broker reconciliation (positions, open orders, P&L)."""

    @abstractmethod
    async def on_tick(
        self,
        ctx: StrategyContext,
        *,
        symbol: str,
        price: float,
        previous_close: float,
        timestamp: Any | None = None,
    ) -> None:
        """Per-quote evaluation. Implementation may submit orders, mutate
        position state, schedule exits, etc."""

    async def on_stop(self, ctx: StrategyContext) -> None:
        """Optional teardown hook. Default is no-op."""
        return None
