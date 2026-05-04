"""On-chain metric parser.

GlassNode returns a list of `{t: unix_ts, v: float}` rows. Convert into
typed `OnChainObservation` records with parsed datetimes; defensive about
missing/null fields the same way the screener and crypto compute layers
are.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class OnChainObservation:
    timestamp: datetime
    value: float | None


def _parse_one(item: dict) -> OnChainObservation | None:
    t = item.get("t")
    if not isinstance(t, (int, float)):
        return None
    try:
        ts = datetime.fromtimestamp(int(t), tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
    raw_v = item.get("v")
    value: float | None
    if raw_v is None:
        value = None
    else:
        try:
            value = float(raw_v)
        except (TypeError, ValueError):
            return None
        if value != value:  # NaN guard
            value = None
    return OnChainObservation(timestamp=ts, value=value)


def parse_metric_payload(rows: list) -> list[OnChainObservation]:
    """Tolerant parser: skips malformed entries, logs DEBUG with skip count."""
    out: list[OnChainObservation] = []
    skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        parsed = _parse_one(row)
        if parsed is None:
            skipped += 1
            continue
        out.append(parsed)
    if skipped:
        logger.debug("GlassNode: skipped %d malformed observation(s)", skipped)
    out.sort(key=lambda o: o.timestamp)
    return out
