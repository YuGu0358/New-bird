"""StrategyContext — the handle passed to strategy lifecycle methods.

Phase 2 keeps this minimal (logger + parameters). Phase 4 adds a broker
handle here so strategies can submit orders without importing alpaca_service
directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models import StrategyExecutionParameters

# Type alias for now — generic enough that any concrete strategy's params
# subclass can be passed. When Phase 4 introduces the Broker interface, this
# will gain a `broker` field.
StrategyParameters = StrategyExecutionParameters


@dataclass
class StrategyContext:
    parameters: StrategyParameters
    logger: logging.Logger
