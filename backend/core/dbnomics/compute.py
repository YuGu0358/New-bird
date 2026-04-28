"""Pure compute helpers for the DBnomics adapter.

DBnomics returns a per-series JSON document with parallel `period` and `value`
arrays plus a few metadata fields. This module turns one such document into a
normalized `DBnomicsSeries` (no I/O, no settings, no logging side-effects
beyond a DEBUG line for non-numeric values).

Period parsing covers the four formats DBnomics is known to emit:
- annual:    "2024"        -> date(2024, 1, 1)
- quarterly: "2024-Q1..Q4" -> date(2024, {1,4,7,10}, 1)
- monthly:   "2024-03"     -> date(2024, 3, 1)
- daily:     "2024-03-15"  -> date(2024, 3, 15)

Anything else -> None (best effort; the verbatim string is preserved on the
observation regardless).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


__all__ = [
    "DBnomicsObservation",
    "DBnomicsSeries",
    "parse_period_to_date",
    "parse_series_doc",
]


_RE_ANNUAL = re.compile(r"^(\d{4})$")
_RE_MONTHLY = re.compile(r"^(\d{4})-(\d{2})$")
_RE_QUARTERLY = re.compile(r"^(\d{4})-Q([1-4])$")
_RE_DAILY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

# Quarter -> first month of that quarter.
_QUARTER_TO_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}


@dataclass
class DBnomicsObservation:
    """A single (period, value) point on a DBnomics series.

    `period` is the verbatim upstream label. `date` is a best-effort
    first-day-of-period parse (None if the format is unrecognised). `value`
    is None for missing observations or for non-numeric upstream entries.
    """

    period: str
    date: date | None = None
    value: float | None = None


@dataclass
class DBnomicsSeries:
    """Normalized DBnomics series — observations sorted ascending by period."""

    provider_code: str
    dataset_code: str
    series_code: str
    series_name: str | None = None
    frequency: str | None = None
    indexed_at: str | None = None
    observations: list[DBnomicsObservation] = field(default_factory=list)


def parse_period_to_date(period: str) -> date | None:
    """Best-effort period -> first-day-of-period date.

    Supported formats: 'YYYY', 'YYYY-MM', 'YYYY-Q[1-4]', 'YYYY-MM-DD'.
    Returns None for unrecognised formats (e.g. ISO weeks 'YYYY-Www',
    semesters 'YYYY-S1', or empty/garbage strings).
    """
    if not isinstance(period, str) or not period:
        return None

    # Daily — most specific first.
    m = _RE_DAILY.match(period)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # Quarterly.
    m = _RE_QUARTERLY.match(period)
    if m:
        year = int(m.group(1))
        quarter = int(m.group(2))
        try:
            return date(year, _QUARTER_TO_MONTH[quarter], 1)
        except (KeyError, ValueError):
            return None

    # Monthly.
    m = _RE_MONTHLY.match(period)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None

    # Annual — least specific last so '2024-03' isn't matched as '2024'.
    m = _RE_ANNUAL.match(period)
    if m:
        try:
            return date(int(m.group(1)), 1, 1)
        except ValueError:
            return None

    return None


def _coerce_value(raw: Any) -> float | None:
    """Convert a raw upstream value to float|None.

    null -> None. Non-numeric (e.g. "NA", strings, dicts) -> None with a
    DEBUG log so unexpected upstream payloads are at least traceable.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        # `bool` is a subclass of `int` — guard explicitly so True/False
        # don't sneak through as 1.0/0.0.
        logger.debug("DBnomics: boolean value coerced to None: %r", raw)
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.debug("DBnomics: non-numeric value coerced to None: %r", raw)
        return None


def parse_series_doc(doc: dict) -> DBnomicsSeries | None:
    """Parse one DBnomics series document into `DBnomicsSeries`.

    Returns None when any of the mandatory keys are missing:
    `provider_code`, `dataset_code`, `series_code`, `period`, `value`.

    Defensive behaviours:
    - period/value length mismatch -> clamp to `min(len(period), len(value))`.
    - `null` value -> observation with value=None.
    - non-numeric value -> observation with value=None and a DEBUG log.
    - observations are sorted ascending by the verbatim period string
      (ISO-8601-style strings sort correctly lexicographically).
    """
    if not isinstance(doc, dict):
        return None

    provider_code = doc.get("provider_code")
    dataset_code = doc.get("dataset_code")
    series_code = doc.get("series_code")
    periods = doc.get("period")
    values = doc.get("value")

    if not isinstance(provider_code, str) or not provider_code:
        return None
    if not isinstance(dataset_code, str) or not dataset_code:
        return None
    if not isinstance(series_code, str) or not series_code:
        return None
    if not isinstance(periods, list) or not isinstance(values, list):
        return None

    n = min(len(periods), len(values))
    observations: list[DBnomicsObservation] = []
    for i in range(n):
        period_raw = periods[i]
        if not isinstance(period_raw, str):
            # Skip rows whose period isn't a string — we can't index by them.
            logger.debug("DBnomics: non-string period skipped: %r", period_raw)
            continue
        observations.append(
            DBnomicsObservation(
                period=period_raw,
                date=parse_period_to_date(period_raw),
                value=_coerce_value(values[i]),
            )
        )

    observations.sort(key=lambda obs: obs.period)

    series_name = doc.get("series_name")
    if series_name is not None and not isinstance(series_name, str):
        series_name = None

    frequency = doc.get("@frequency")
    if frequency is not None and not isinstance(frequency, str):
        frequency = None

    indexed_at = doc.get("indexed_at")
    if indexed_at is not None and not isinstance(indexed_at, str):
        indexed_at = None

    return DBnomicsSeries(
        provider_code=provider_code,
        dataset_code=dataset_code,
        series_code=series_code,
        series_name=series_name,
        frequency=frequency,
        indexed_at=indexed_at,
        observations=observations,
    )
