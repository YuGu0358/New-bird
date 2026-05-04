"""ContextVar-backed correlation-id store.

Used by:
- HTTP middleware to attach a request ID to every log line emitted while
  the request is in flight.
- Logging filter (logging_setup.py) to inject the current id into JSON output.
- Strategy runner / backtest engine to scope their long-running operations.
"""
from __future__ import annotations

import contextvars

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def get_correlation_id() -> str:
    return correlation_id_var.get()


def set_correlation_id(value: str) -> contextvars.Token[str]:
    """Returns a Token. Pass to `correlation_id_var.reset(token)` to undo."""
    return correlation_id_var.set(value)
