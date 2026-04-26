"""Strategy → execution layer signal types.

Strategies emit `OrderIntent` records describing *what* they want to do. The
runner / broker layer translates intents into actual orders. Keeping intents
separate from broker calls is what makes backtesting (Phase 3) possible: the
backtest engine consumes the same intents but resolves them against historical
bars instead of an Alpaca account.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SignalType(str, Enum):
    ENTRY = "entry"
    ADD_ON = "add_on"
    EXIT_TAKE_PROFIT = "exit_take_profit"
    EXIT_STOP_LOSS = "exit_stop_loss"
    EXIT_TIMEOUT = "exit_timeout"
    EXIT_MANUAL = "exit_manual"


@dataclass(frozen=True)
class OrderIntent:
    """A strategy's request to open or close a position.

    Either `notional` or `qty` is set, never both. The runner decides which
    broker call to use based on which is present.
    """

    symbol: str
    side: str  # "buy" | "sell"
    signal_type: SignalType
    reason: str
    notional: Optional[float] = None
    qty: Optional[float] = None
    requested_at: Optional[datetime] = None
