"""Broker abstraction package."""
from __future__ import annotations

import logging

from core.broker.alpaca import AlpacaBroker
from core.broker.base import Broker
from core.broker.ibkr import IBKRBroker

__all__ = ["AlpacaBroker", "Broker", "IBKRBroker", "get_broker"]

logger = logging.getLogger(__name__)

# Default backend used when BROKER_BACKEND is unset or unrecognized.
_DEFAULT_BACKEND = "alpaca"

_KNOWN_BACKENDS = {"alpaca", "ibkr"}


def get_broker() -> Broker:
    """Return the broker selected by ``BROKER_BACKEND``.

    Reads the setting via :mod:`app.runtime_settings` so DB-stored values and
    ``.env`` overrides both work. Defaults to :class:`AlpacaBroker`; returns
    :class:`IBKRBroker` when ``BROKER_BACKEND='ibkr'``. Unknown values fall
    back to Alpaca with a WARNING log so the operator can spot a typo.
    """
    from app import runtime_settings

    raw = (runtime_settings.get_setting("BROKER_BACKEND", _DEFAULT_BACKEND) or "").strip().lower()
    if raw == "ibkr":
        return IBKRBroker()
    if raw in {"", "alpaca", _DEFAULT_BACKEND}:
        return AlpacaBroker()

    logger.warning(
        "Unknown BROKER_BACKEND %r; falling back to AlpacaBroker. "
        "Supported values: %s.",
        raw,
        sorted(_KNOWN_BACKENDS),
    )
    return AlpacaBroker()
