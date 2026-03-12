"""Minimal CLI-Anything style REPL skin for the trading platform harness."""

from __future__ import annotations

import os
import sys

_RESET = "\033[0m"
_BOLD = "\033[1m"
_CYAN = "\033[38;5;80m"
_GREEN = "\033[38;5;78m"
_RED = "\033[38;5;196m"
_YELLOW = "\033[38;5;220m"
_GRAY = "\033[38;5;245m"


class ReplSkin:
    """Small styling helper for the interactive CLI mode."""

    def __init__(self, software: str, version: str = "1.0.0") -> None:
        self.software = software
        self.version = version
        self._color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty() and not os.getenv("NO_COLOR")

    def _paint(self, code: str, text: str) -> str:
        if not self._color:
            return text
        return f"{code}{text}{_RESET}"

    def print_banner(self) -> None:
        title = self._paint(_CYAN + _BOLD, f"cli-anything · {self.software}")
        version = self._paint(_GRAY, f"v{self.version}")
        print(title)
        print(version)
        print("Type help for commands, exit to quit.")
        print()

    def prompt(self) -> str:
        return self._paint(_CYAN + _BOLD, "trading-platform") + self._paint(_GRAY, " > ")

    def success(self, message: str) -> None:
        print(self._paint(_GREEN, message))

    def error(self, message: str) -> None:
        print(self._paint(_RED, message))

    def warning(self, message: str) -> None:
        print(self._paint(_YELLOW, message))
