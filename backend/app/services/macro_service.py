"""Macro indicator service — wraps the core engine for FastAPI.

Responsibilities:
- Build a `FREDClient` lazily from `runtime_settings`
- Fetch the seed list, compute signal levels, return a normalized payload
- Cache by `(code, day)` so the dashboard refresh hits FRED at most once
  per day per indicator. The response is also cached for 30 minutes overall
  so a user who reloads the page repeatedly doesn't refetch the lot.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app import runtime_settings
from core.macro import (
    FREDClient,
    FREDConfigError,
    FREDObservation,
    SEED_INDICATORS,
    evaluate_signal,
)
from core.macro.fred import yoy_pct_change

logger = logging.getLogger(__name__)

_DASHBOARD_CACHE_TTL = timedelta(minutes=30)
_dashboard_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}

# Per-series last fetched date — avoids hitting FRED twice on the same day.
_series_cache: dict[str, tuple[date, list[FREDObservation]]] = {}


def _get_client() -> FREDClient:
    api_key = runtime_settings.get_setting("FRED_API_KEY", "")
    if not api_key:
        raise FREDConfigError(
            "FRED_API_KEY is missing. Add it on the Settings page (free key from "
            "https://fredaccount.stlouisfed.org/apikeys)."
        )
    return FREDClient(api_key=api_key)


def _fetch_series_blocking(client: FREDClient, series_id: str, lookback_days: int) -> list[FREDObservation]:
    today = date.today()
    cached = _series_cache.get(series_id)
    if cached and cached[0] == today:
        return cached[1]
    start = today - timedelta(days=lookback_days)
    obs = client.fetch_series(series_id, start=start)
    if obs:
        _series_cache[series_id] = (today, obs)
    return obs


async def _fetch_series(client: FREDClient, series_id: str, lookback_days: int = 365 * 6) -> list[FREDObservation]:
    return await asyncio.to_thread(_fetch_series_blocking, client, series_id, lookback_days)


def _last_observation(obs: list[FREDObservation]) -> FREDObservation | None:
    for entry in reversed(obs):
        if entry.value is not None:
            return entry
    return None


def _previous_close(obs: list[FREDObservation], current: FREDObservation) -> float | None:
    for entry in reversed(obs):
        if entry.value is None:
            continue
        if entry.as_of >= current.as_of:
            continue
        return entry.value
    return None


async def get_dashboard(*, force: bool = False) -> dict[str, Any]:
    """Return the full macro dashboard payload.

    Raises FREDConfigError if the key is missing — the router maps this to
    503 with a friendly message.
    """
    cached = _dashboard_cache.get("default")
    now = datetime.now(timezone.utc)
    if not force and cached and now - cached[0] <= _DASHBOARD_CACHE_TTL:
        return cached[1]

    client = _get_client()
    indicators: list[dict[str, Any]] = []
    ensemble_total = 0
    ensemble_signals: dict[str, int] = {"ok": 0, "warn": 0, "danger": 0, "neutral": 0}

    for seed in SEED_INDICATORS:
        try:
            if seed.source == "FRED":
                obs = await _fetch_series(client, seed.code)
                series = obs
            elif seed.source == "DERIVED" and seed.derive_kind == "yoy_pct":
                base = await _fetch_series(client, seed.base_series or seed.code)
                series = yoy_pct_change(base) if base else []
            else:
                series = []
        except Exception as exc:  # noqa: BLE001 — FRED outages mustn't blank the page
            logger.warning("macro fetch %s failed: %s", seed.code, exc)
            series = []

        last = _last_observation(series)
        previous = _previous_close(series, last) if last else None
        change = None
        if last and previous and previous != 0:
            change = (last.value - previous) * (1.0 if "yoy" in seed.code.lower() else 1.0)
        signal = evaluate_signal(last.value if last else None, seed.default_thresholds)

        # Trim spark series to ~ last 90 daily points (or all monthly points)
        sparkline = [
            {"as_of": o.as_of.isoformat(), "value": o.value}
            for o in series[-90:]
            if o.value is not None
        ]

        if seed.is_ensemble_core:
            ensemble_total += 1
            ensemble_signals[signal] = ensemble_signals.get(signal, 0) + 1

        indicators.append(
            {
                "code": seed.code,
                "category": seed.category,
                "source": seed.source,
                "is_ensemble_core": seed.is_ensemble_core,
                "i18n_key": seed.i18n_key,
                "description_key": seed.description_key,
                "unit": seed.unit,
                "default_thresholds": dict(seed.default_thresholds),
                "value": last.value if last else None,
                "as_of": last.as_of.isoformat() if last else None,
                "change_abs": change,
                "signal": signal,
                "sparkline": sparkline,
            }
        )

    payload = {
        "generated_at": now,
        "indicators": indicators,
        "ensemble": {
            "total_core": ensemble_total,
            "signals": ensemble_signals,
        },
    }
    _dashboard_cache["default"] = (now, payload)
    return payload


def configured() -> bool:
    """Lightweight check used by Settings page status dots."""
    return bool(runtime_settings.get_setting("FRED_API_KEY", ""))
