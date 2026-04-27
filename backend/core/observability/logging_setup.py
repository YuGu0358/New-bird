"""JSON-line logging configuration.

Each record becomes one JSON object on stdout with:
    timestamp, level, logger, message, correlation_id, plus any extras
    passed via `logger.info("...", extra={"key": value})`.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from core.observability.correlation import get_correlation_id


_RESERVED_LOGRECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message",
}


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id() or None,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Attach any extras (anything on the record we didn't reserve).
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD_KEYS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Replace the root handler with a JSON-line stdout handler."""
    root = logging.getLogger()
    root.setLevel(level)
    # Remove any pre-existing handlers (uvicorn injects its own, which we
    # want to keep distinct — uvicorn writes to stderr, our app handler to
    # stdout).
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLineFormatter())
    handler.setLevel(level)
    # Add but don't displace uvicorn's handler set during its own startup.
    if not any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, JsonLineFormatter) for h in root.handlers):
        root.addHandler(handler)
