"""DataHub exception hierarchy."""
from __future__ import annotations


class BusError(Exception):
    """Base for every DataHub failure."""


class UnknownTopicError(BusError):
    """Raised when a publish targets a topic that was never registered."""


class SubscriberClosedError(BusError):
    """Raised when an already-unsubscribed token is unsubscribed again."""
