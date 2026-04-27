"""AST whitelist validator — accepts safe code, rejects everything dangerous."""
from __future__ import annotations

import pytest

from core.code_loader.validator import (
    ValidationError,
    validate_strategy_source,
)


_CLEAN_SAMPLE = '''\
from __future__ import annotations
from datetime import datetime
from typing import Any

from core.strategy import Strategy, register_strategy
from app.models import StrategyExecutionParameters


@register_strategy("clean_strategy_v1")
class CleanStrategy(Strategy):
    description = "Clean test strategy."

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


def test_clean_code_passes() -> None:
    validate_strategy_source(_CLEAN_SAMPLE)  # no exception


def test_rejects_import_os() -> None:
    code = "import os\n"
    with pytest.raises(ValidationError, match="forbidden import: os"):
        validate_strategy_source(code)


def test_rejects_subprocess() -> None:
    code = "from subprocess import run\n"
    with pytest.raises(ValidationError, match="forbidden import: subprocess"):
        validate_strategy_source(code)


def test_rejects_requests() -> None:
    code = "import requests\n"
    with pytest.raises(ValidationError, match="forbidden import: requests"):
        validate_strategy_source(code)


def test_rejects_socket() -> None:
    code = "import socket\n"
    with pytest.raises(ValidationError, match="forbidden import: socket"):
        validate_strategy_source(code)


def test_rejects_eval_call() -> None:
    code = "x = eval('1+1')\n"
    with pytest.raises(ValidationError, match="forbidden builtin: eval"):
        validate_strategy_source(code)


def test_rejects_exec_call() -> None:
    code = "exec('print(1)')\n"
    with pytest.raises(ValidationError, match="forbidden builtin: exec"):
        validate_strategy_source(code)


def test_rejects_compile_call() -> None:
    code = "compile('1', '<>', 'eval')\n"
    with pytest.raises(ValidationError, match="forbidden builtin: compile"):
        validate_strategy_source(code)


def test_rejects_dunder_import() -> None:
    code = "x = __import__('os')\n"
    with pytest.raises(ValidationError, match="forbidden builtin: __import__"):
        validate_strategy_source(code)


def test_rejects_open_call() -> None:
    code = "open('/etc/passwd')\n"
    with pytest.raises(ValidationError, match="forbidden builtin: open"):
        validate_strategy_source(code)


def test_rejects_dunder_class_attribute() -> None:
    code = "x = (1).__class__.__bases__\n"
    with pytest.raises(ValidationError, match="forbidden attribute"):
        validate_strategy_source(code)


def test_rejects_dunder_globals() -> None:
    code = "g = (lambda: None).__globals__\n"
    with pytest.raises(ValidationError, match="forbidden attribute"):
        validate_strategy_source(code)


def test_rejects_oversized_code() -> None:
    code = _CLEAN_SAMPLE + "\n# pad\n" + ("x = 1\n" * 30_000)
    with pytest.raises(ValidationError, match="too large"):
        validate_strategy_source(code)


def test_rejects_no_strategy_subclass() -> None:
    code = '''\
from core.strategy import register_strategy

@register_strategy("nope")
class Nope:
    pass
'''
    with pytest.raises(ValidationError, match="must define a class"):
        validate_strategy_source(code)


def test_rejects_syntax_error() -> None:
    code = "def bad(:\n    pass\n"
    with pytest.raises(ValidationError, match="syntax error"):
        validate_strategy_source(code)
