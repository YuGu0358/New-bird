"""Sandbox loader — validates user source then exec's it under restricted
globals so the @register_strategy decorator runs and inserts the class
into the framework registry.

Caller must supply `expected_name` — the slot the strategy is meant to
register under. We check that the registry gained exactly that name to
prevent users from accidentally (or intentionally) registering a name
that collides with a built-in strategy or another user upload.
"""
from __future__ import annotations

import builtins
from typing import Any

from core.code_loader.validator import (
    ALLOWED_IMPORT_PREFIXES,
    ValidationError,
    validate_strategy_source,
)
from core.strategy.base import Strategy
from core.strategy.registry import (
    StrategyAlreadyRegisteredError,
    default_registry,
)


class SandboxLoadError(RuntimeError):
    """Validation passed but exec / registration step failed."""


# Builtins we expose inside user code. Most are safe; the dangerous ones
# (eval, exec, compile, __import__, open) are already AST-rejected, but we
# still strip them here as defense in depth.
_SAFE_BUILTINS: set[str] = {
    # Type constructors
    "bool", "int", "float", "complex", "str", "bytes", "bytearray",
    "list", "tuple", "dict", "set", "frozenset", "type", "object",
    # Iteration / numeric helpers
    "range", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "len", "sum", "min", "max", "abs", "round", "any", "all",
    "isinstance", "issubclass", "hasattr", "getattr",
    "iter", "next", "id", "repr", "format", "print",
    # Exception classes
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "RuntimeError", "NotImplementedError",
    "ZeroDivisionError", "ArithmeticError", "StopIteration",
    "AssertionError", "ImportError", "LookupError",
    # Other
    "True", "False", "None", "NotImplemented", "Ellipsis",
    "property", "staticmethod", "classmethod", "super",
    "callable", "slice", "divmod", "pow", "hash",
    "frozenset", "memoryview",
    # Required by Python's class machinery — without these, `class` keyword
    # cannot construct types and decorators cannot resolve names.
    "__build_class__",
}


def _is_allowed_import(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in ALLOWED_IMPORT_PREFIXES
    )


def _restricted_import(name: str, globals=None, locals=None, fromlist=(), level=0):
    """Replacement for builtins.__import__ that enforces our whitelist at
    runtime — defense in depth on top of the static AST check."""
    if level != 0:
        raise ImportError("relative imports are not allowed in user strategies")
    if not _is_allowed_import(name):
        raise ImportError(f"forbidden import at runtime: {name}")
    return __import__(name, globals, locals, fromlist, level)


def _build_restricted_builtins() -> dict[str, Any]:
    safe = {name: getattr(builtins, name) for name in _SAFE_BUILTINS if hasattr(builtins, name)}
    safe["__import__"] = _restricted_import
    return safe


def load_strategy_from_source(source: str, *, expected_name: str) -> type[Strategy]:
    """Validate, exec, register. Returns the registered Strategy subclass.

    Steps:
    1. AST validation (ValidationError → SandboxLoadError).
    2. Compile + exec under restricted globals — the @register_strategy
       decorator runs during this step.
    3. Verify the expected name now resolves in the registry.
    4. Return the class.

    On any failure, registry state is rolled back to what it was before.
    """
    if not expected_name or not expected_name.strip():
        raise SandboxLoadError("expected_name must be a non-empty string")

    try:
        validate_strategy_source(source)
    except ValidationError as exc:
        raise SandboxLoadError(str(exc)) from exc

    snapshot = set(default_registry.list_names())

    try:
        compiled = compile(source, f"<user_strategy:{expected_name}>", "exec")
    except SyntaxError as exc:
        raise SandboxLoadError(f"syntax error: {exc.msg}") from exc

    restricted_globals: dict[str, Any] = {
        "__builtins__": _build_restricted_builtins(),
        "__name__": f"user_strategy_{expected_name}",
    }

    try:
        exec(compiled, restricted_globals)  # noqa: S102 — sandboxed by design
    except StrategyAlreadyRegisteredError:
        raise
    except Exception as exc:
        _rollback_registry_to(snapshot)
        raise SandboxLoadError(f"exec failed: {exc!r}") from exc

    new_names = set(default_registry.list_names()) - snapshot
    if expected_name not in new_names:
        _rollback_registry_to(snapshot)
        if not new_names:
            raise SandboxLoadError(
                f"source did not register any strategy "
                f"(expected name={expected_name!r}). "
                f"Make sure your class is decorated with @register_strategy({expected_name!r})."
            )
        raise SandboxLoadError(
            f"source registered {sorted(new_names)} but expected name {expected_name!r}"
        )

    cls = default_registry.get(expected_name)
    return cls


def unregister_strategy(name: str) -> None:
    """Remove a strategy from the registry. Used to delete or hot-reload uploads."""
    default_registry._strategies.pop(name, None)


def _rollback_registry_to(snapshot: set[str]) -> None:
    """Drop any registry entries added after `snapshot` was taken."""
    current = set(default_registry.list_names())
    for added in current - snapshot:
        default_registry._strategies.pop(added, None)
