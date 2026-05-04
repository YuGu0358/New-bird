"""Sandbox loader — exec validated source + register strategy class."""
from __future__ import annotations

import pytest

from core.agents import get_persona  # unrelated, just to ensure imports work
from core.code_loader.sandbox import (
    SandboxLoadError,
    load_strategy_from_source,
    unregister_strategy,
)
from core.strategy.registry import default_registry


_VALID_SAMPLE = '''\
from __future__ import annotations
from datetime import datetime

from core.strategy import Strategy, register_strategy
from app.models import StrategyExecutionParameters


@register_strategy("__test_user_strategy_a")
class UserStrategyA(Strategy):
    description = "Test user strategy A."

    @classmethod
    def parameters_schema(cls):
        return StrategyExecutionParameters

    def __init__(self, parameters, *, broker=None) -> None:
        super().__init__(parameters)
        self._broker = broker

    def universe(self) -> list[str]:
        return list(self.parameters.universe_symbols)

    async def on_start(self, ctx) -> None:
        return None

    async def on_periodic_sync(self, ctx, now: datetime) -> None:
        return None

    async def on_tick(self, ctx, *, symbol, price, previous_close, timestamp=None):
        return None
'''


@pytest.fixture(autouse=True)
def _cleanup_registry():
    """Strip any test-prefixed strategy from registry between cases."""
    yield
    for name in list(default_registry.list_names()):
        if name.startswith("__test_"):
            default_registry._strategies.pop(name, None)


def test_load_clean_strategy_registers() -> None:
    cls = load_strategy_from_source(_VALID_SAMPLE, expected_name="__test_user_strategy_a")
    assert cls.name == "__test_user_strategy_a"
    assert default_registry.get("__test_user_strategy_a") is cls


def test_unregister_removes_from_registry() -> None:
    load_strategy_from_source(_VALID_SAMPLE, expected_name="__test_user_strategy_a")
    unregister_strategy("__test_user_strategy_a")
    assert "__test_user_strategy_a" not in default_registry.list_names()


def test_load_rejects_dangerous_code() -> None:
    bad = "import os\n" + _VALID_SAMPLE
    with pytest.raises(SandboxLoadError, match="forbidden import"):
        load_strategy_from_source(bad, expected_name="__test_user_strategy_a")


def test_load_rejects_when_no_strategy_registers() -> None:
    code = '''\
from core.strategy import Strategy

class _NotRegistered(Strategy):
    @classmethod
    def parameters_schema(cls): pass
    def universe(self): return []
    async def on_start(self, ctx): pass
    async def on_periodic_sync(self, ctx, now): pass
    async def on_tick(self, ctx, *, symbol, price, previous_close, timestamp=None): pass
'''
    with pytest.raises(SandboxLoadError, match="did not register"):
        load_strategy_from_source(code, expected_name="__test_x")


def test_load_rejects_name_mismatch() -> None:
    with pytest.raises(SandboxLoadError, match="expected name"):
        load_strategy_from_source(_VALID_SAMPLE, expected_name="__test_other_name")
