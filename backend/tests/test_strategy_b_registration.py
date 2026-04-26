"""Verify Strategy B registers correctly via the new framework."""
from __future__ import annotations

from app.models import StrategyExecutionParameters

# Import the strategies package to trigger @register_strategy decorators.
import strategies  # noqa: F401  pyright: ignore

from core.strategy import default_registry
from core.strategy.base import Strategy


def test_strategy_b_is_registered() -> None:
    cls = default_registry.get("strategy_b_v1")
    assert issubclass(cls, Strategy)
    assert cls.name == "strategy_b_v1"


def test_strategy_b_parameters_schema_is_strategy_execution_parameters() -> None:
    cls = default_registry.get("strategy_b_v1")
    assert cls.parameters_schema() is StrategyExecutionParameters


def test_strategy_b_can_be_instantiated_with_default_parameters() -> None:
    cls = default_registry.get("strategy_b_v1")
    parameters = StrategyExecutionParameters(
        universe_symbols=["AAPL", "MSFT"],
        entry_drop_percent=2.0,
        add_on_drop_percent=2.0,
        initial_buy_notional=1000.0,
        add_on_buy_notional=100.0,
        max_daily_entries=3,
        max_add_ons=3,
        take_profit_target=80.0,
        stop_loss_percent=12.0,
        max_hold_days=30,
    )
    strategy = cls(parameters)
    assert strategy.universe() == ["AAPL", "MSFT"]
