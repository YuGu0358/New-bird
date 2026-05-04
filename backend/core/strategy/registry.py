"""Strategy registry + @register_strategy decorator.

Concrete strategies decorate themselves with @register_strategy("name") at
import time. Importing the `backend/strategies` package triggers all
decorators, populating the module-level `default_registry`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:
    from core.strategy.base import Strategy


class StrategyAlreadyRegisteredError(RuntimeError):
    """Raised when two classes try to register the same name."""


class StrategyNotFoundError(KeyError):
    """Raised when looking up an unregistered strategy name."""


class StrategyRegistry:
    """Holds the mapping from strategy-name strings to Strategy subclasses."""

    def __init__(self) -> None:
        self._strategies: dict[str, type["Strategy"]] = {}

    def register(self, name: str, strategy_cls: type["Strategy"]) -> None:
        if name in self._strategies and self._strategies[name] is not strategy_cls:
            raise StrategyAlreadyRegisteredError(
                f"Strategy name {name!r} is already registered to "
                f"{self._strategies[name].__module__}.{self._strategies[name].__name__}"
            )
        self._strategies[name] = strategy_cls

    def get(self, name: str) -> type["Strategy"]:
        if name not in self._strategies:
            raise StrategyNotFoundError(f"No strategy registered as {name!r}")
        return self._strategies[name]

    def list_names(self) -> list[str]:
        return sorted(self._strategies.keys())

    def items(self) -> list[tuple[str, type["Strategy"]]]:
        return sorted(self._strategies.items())


default_registry = StrategyRegistry()


T = TypeVar("T", bound="type[Strategy]")


def register_strategy(name: str) -> Callable[[T], T]:
    """Class decorator: register the decorated Strategy subclass under `name`."""

    def _decorator(cls: T) -> T:
        cls.name = name  # type: ignore[attr-defined]
        default_registry.register(name, cls)
        return cls

    return _decorator
