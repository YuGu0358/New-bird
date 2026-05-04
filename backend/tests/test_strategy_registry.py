"""Strategy registry behavior."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.models import StrategyExecutionParameters

from core.strategy.base import Strategy
from core.strategy.context import StrategyContext
from core.strategy.registry import (
    StrategyAlreadyRegisteredError,
    StrategyNotFoundError,
    StrategyRegistry,
    register_strategy,
)


def _make_dummy_strategy(name: str) -> type[Strategy]:
    class DummyStrategy(Strategy):
        @classmethod
        def parameters_schema(cls):
            return StrategyExecutionParameters

        def universe(self) -> list[str]:
            return self.parameters.universe_symbols

        async def on_start(self, ctx: StrategyContext) -> None:
            pass

        async def on_periodic_sync(self, ctx, now: datetime) -> None:
            pass

        async def on_tick(self, ctx, *, symbol, price, previous_close, timestamp=None):
            pass

    DummyStrategy.name = name
    return DummyStrategy


def test_register_and_lookup() -> None:
    registry = StrategyRegistry()
    cls = _make_dummy_strategy("dummy_v1")
    registry.register("dummy_v1", cls)
    assert registry.get("dummy_v1") is cls
    assert "dummy_v1" in registry.list_names()


def test_duplicate_registration_raises() -> None:
    registry = StrategyRegistry()
    registry.register("dup", _make_dummy_strategy("dup"))
    with pytest.raises(StrategyAlreadyRegisteredError):
        registry.register("dup", _make_dummy_strategy("dup"))


def test_unknown_lookup_raises() -> None:
    registry = StrategyRegistry()
    with pytest.raises(StrategyNotFoundError):
        registry.get("nonexistent")


def test_decorator_registers_into_default_registry() -> None:
    """The @register_strategy decorator binds to the module-level registry."""
    from core.strategy import registry as registry_module

    cls = _make_dummy_strategy("decorator_test_v1")
    decorated = register_strategy("decorator_test_v1")(cls)
    assert decorated is cls
    assert registry_module.default_registry.get("decorator_test_v1") is cls
    # Cleanup so this test is idempotent across runs.
    registry_module.default_registry._strategies.pop("decorator_test_v1", None)
