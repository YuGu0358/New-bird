"""FRED API client (St. Louis Fed) — primary macro data source.

Free key: https://fredaccount.stlouisfed.org/apikeys

NewBird reads the key from `runtime_settings` (the same place the user fills
on the Settings page) so we don't force them into a `.env` file. Tests inject
an explicit key.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FRED_BASE_URL = "https://api.stlouisfed.org/fred"


class FREDConfigError(RuntimeError):
    """Raised when FRED_API_KEY is missing — caller should surface in UI."""


@dataclass(frozen=True)
class FREDObservation:
    series_id: str
    as_of: date
    value: float | None  # None = "." in FRED CSV (missing)


class FREDClient:
    """Minimal synchronous FRED REST client.

    Keep it sync — we run from FastAPI background calls via `asyncio.to_thread`
    in the service layer. That keeps this module free of asyncio plumbing.
    """

    def __init__(self, api_key: str | None) -> None:
        if not api_key:
            raise FREDConfigError(
                "FRED_API_KEY is missing. Get a free key at "
                "https://fredaccount.stlouisfed.org/apikeys and add it under Settings."
            )
        self.api_key = api_key

    def fetch_series(
        self,
        series_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[FREDObservation]:
        """Pull observations for a FRED series.

        Args:
            series_id: e.g. "DGS10", "CPIAUCSL", "WALCL".
            start: observation_start (default = series origin).
            end: observation_end (default = today).
            limit: cap rows (default uncapped). Pass e.g. 1500 for ~6 years
                of daily data when you don't need full history.
        """
        params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "asc",
        }
        if start:
            params["observation_start"] = start.isoformat()
        if end:
            params["observation_end"] = end.isoformat()
        if limit:
            params["limit"] = int(limit)

        url = f"{FRED_BASE_URL}/series/observations"
        try:
            resp = httpx.get(url, params=params, timeout=15.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("FRED fetch_series(%s) failed: %s", series_id, exc)
            return []

        try:
            payload = resp.json()
        except ValueError:
            logger.warning("FRED returned non-JSON for %s", series_id)
            return []

        obs: list[FREDObservation] = []
        for row in payload.get("observations", []):
            try:
                d = datetime.fromisoformat(row["date"]).date()
            except (KeyError, ValueError):
                continue
            raw = row.get("value", ".")
            value = None if raw in (".", "", None) else float(raw)
            obs.append(FREDObservation(series_id=series_id, as_of=d, value=value))
        return obs


def yoy_pct_change(observations: list[FREDObservation]) -> list[FREDObservation]:
    """Compute trailing 12-month YoY % change from monthly observations.

    Used for CPI / PCE-style series where we want YoY rather than the raw
    index level. The look-back is fuzzy (335..395 days) to handle weekends
    and irregular reporting.
    """
    by_date = {o.as_of: o.value for o in observations if o.value is not None}
    out: list[FREDObservation] = []
    for d, v in sorted(by_date.items()):
        prior = None
        for delta in range(335, 396):
            from datetime import timedelta

            cand = d - timedelta(days=delta)
            if cand in by_date:
                prior = by_date[cand]
                break
        if prior and prior != 0:
            pct = (v / prior - 1) * 100
            out.append(FREDObservation(series_id=observations[0].series_id, as_of=d, value=pct))
    return out
