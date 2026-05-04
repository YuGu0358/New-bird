"""Strategy B as the first registered concrete strategy.

Wraps the existing StrategyBEngine without changing its trading logic. The
wrapper translates the framework's lifecycle methods into engine method calls
and converts API-level StrategyExecutionParameters into the engine's
StrategyExecutionConfig dataclass.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models import StrategyExecutionParameters

from core.broker import Broker
from core.strategy.base import Strategy
from core.strategy.context import StrategyContext
from core.strategy.registry import register_strategy

from strategy.strategy_b import StrategyBEngine, StrategyExecutionConfig


def _to_engine_config(
    params: StrategyExecutionParameters,
    *,
    strategy_name: str = "strategy_b_v1",
) -> StrategyExecutionConfig:
    """Translate API-level params to the engine's internal dataclass."""
    return StrategyExecutionConfig(
        universe=list(params.universe_symbols),
        entry_drop_threshold=params.entry_drop_percent / 100,
        add_on_drop_threshold=params.add_on_drop_percent / 100,
        initial_buy_notional=params.initial_buy_notional,
        add_on_buy_notional=params.add_on_buy_notional,
        max_daily_entries=params.max_daily_entries,
        max_add_ons=params.max_add_ons,
        take_profit_target=params.take_profit_target,
        stop_loss_threshold=params.stop_loss_percent / 100,
        max_hold_days=params.max_hold_days,
        strategy_name=strategy_name,
    )


@register_strategy("strategy_b_v1")
class StrategyB(Strategy):
    """Fixed-notional dollar-cost-down strategy.

    Buys 1000 USD when a name in the universe drops 2% from the previous
    close, adds 100 USD per additional 2% drop (max 3 add-ons), exits at a
    fixed 80 USD profit target, 12% capital stop-loss, or 30-day timeout.
    """

    description = "Fixed-notional dollar-cost-down strategy on the default 20-name universe."

    @classmethod
    def parameters_schema(cls) -> type[StrategyExecutionParameters]:
        return StrategyExecutionParameters

    def __init__(
        self,
        parameters: StrategyExecutionParameters,
        *,
        broker: Broker | None = None,
    ) -> None:
        super().__init__(parameters)
        self._engine = StrategyBEngine(_to_engine_config(parameters), broker=broker)

    @property
    def engine(self) -> StrategyBEngine:
        """Expose the underlying engine for the runner to drive."""
        return self._engine

    def universe(self) -> list[str]:
        return list(self._engine.config.universe)

    async def on_start(self, ctx: StrategyContext) -> None:
        await self._engine.sync_from_broker()
        await self._engine.evaluate_broker_positions()

    async def on_periodic_sync(self, ctx: StrategyContext, now: datetime) -> None:
        await self._engine.sync_from_broker()
        await self._engine.evaluate_broker_positions(now)

    async def on_tick(
        self,
        ctx: StrategyContext,
        *,
        symbol: str,
        price: float,
        previous_close: float,
        timestamp: Any | None = None,
    ) -> None:
        await self._engine.process_tick(
            symbol=symbol,
            current_price=price,
            previous_close=previous_close,
            timestamp=timestamp,
        )
