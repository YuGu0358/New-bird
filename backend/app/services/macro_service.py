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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import runtime_settings
from app.db import MacroThresholdOverride
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


def _invalidate_dashboard_cache() -> None:
    """Drop the cached dashboard payload so the next read recomputes signals."""
    _dashboard_cache.clear()


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


async def _load_overrides(session: AsyncSession | None) -> dict[str, dict[str, Any]]:
    """Read the threshold-override map from the DB.

    Returns {} when no session is provided (test paths) or no overrides exist.
    """
    if session is None:
        return {}
    rows = (await session.execute(select(MacroThresholdOverride))).scalars().all()
    return {row.indicator_code: dict(row.thresholds_json or {}) for row in rows}


async def get_dashboard(
    *, force: bool = False, session: AsyncSession | None = None
) -> dict[str, Any]:
    """Return the full macro dashboard payload.

    Raises FREDConfigError if the key is missing — the router maps this to
    503 with a friendly message.
    """
    cached = _dashboard_cache.get("default")
    now = datetime.now(timezone.utc)
    if not force and cached and now - cached[0] <= _DASHBOARD_CACHE_TTL:
        return cached[1]

    client = _get_client()
    overrides = await _load_overrides(session)
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

        # Effective thresholds = user override (if any) OR the seed default.
        # User overrides are an opaque JSON blob — we don't validate they
        # match the spec; the threshold engine returns "neutral" if it doesn't
        # like what it sees.
        effective_thresholds = overrides.get(seed.code) or dict(seed.default_thresholds)
        signal = evaluate_signal(last.value if last else None, effective_thresholds)

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
                "thresholds": effective_thresholds,
                "thresholds_overridden": seed.code in overrides,
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


# ---------------------------------------------------------------------------
# Threshold override CRUD
# ---------------------------------------------------------------------------


_VALID_DIRECTIONS = {"higher_is_worse", "higher_is_better", "informational"}


def _validate_thresholds(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce and validate a threshold-spec payload.

    Accepts the same shape as `default_thresholds` on each indicator:
        {"ok_max": float, "warn_max": float, "danger_max": float,
         "direction": "higher_is_worse"|"higher_is_better"|"informational"}

    Returns a clean copy. Raises ValueError on bad input.
    """
    direction = str(payload.get("direction", "")).strip()
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(_VALID_DIRECTIONS)}, got {direction!r}"
        )
    out: dict[str, Any] = {"direction": direction}
    if direction == "informational":
        return out

    for key in ("ok_max", "warn_max", "danger_max"):
        if key not in payload or payload[key] is None:
            raise ValueError(f"{key} is required for direction={direction}")
        try:
            out[key] = float(payload[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a number") from exc
    return out


def _seed_for(code: str):
    for seed in SEED_INDICATORS:
        if seed.code == code:
            return seed
    return None


async def upsert_threshold_override(
    session: AsyncSession,
    *,
    code: str,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Create-or-update an override for one indicator. Recomputes signals."""
    seed = _seed_for(code)
    if seed is None:
        raise KeyError(code)

    cleaned = _validate_thresholds(thresholds)
    existing = (
        await session.execute(
            select(MacroThresholdOverride).where(
                MacroThresholdOverride.indicator_code == code
            )
        )
    ).scalars().first()

    if existing is None:
        existing = MacroThresholdOverride(indicator_code=code, thresholds_json=cleaned)
        session.add(existing)
    else:
        existing.thresholds_json = cleaned
        existing.updated_at = datetime.now(timezone.utc)
    await session.commit()
    _invalidate_dashboard_cache()
    return {"code": code, "thresholds": cleaned}


async def delete_threshold_override(session: AsyncSession, *, code: str) -> bool:
    seed = _seed_for(code)
    if seed is None:
        raise KeyError(code)
    existing = (
        await session.execute(
            select(MacroThresholdOverride).where(
                MacroThresholdOverride.indicator_code == code
            )
        )
    ).scalars().first()
    if existing is None:
        return False
    await session.delete(existing)
    await session.commit()
    _invalidate_dashboard_cache()
    return True
