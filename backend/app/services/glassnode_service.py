"""GlassNode on-chain metrics adapter (opt-in).

Pattern mirrors `coingecko_service`: setting gate before cache, 5-min
cache, cache fallback on httpx error, async httpx client.

GlassNode requires both an API key AND an enabled toggle; only the
toggle gate is checked here — a missing key surfaces as a 401 from the
upstream, which our error handler treats like any other transient
failure (cache fallback if available, RuntimeError otherwise).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app import runtime_settings
from core.onchain import OnChainObservation, parse_metric_payload

logger = logging.getLogger(__name__)


_CACHE_TTL = timedelta(minutes=5)
_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=4.0)
_DEFAULT_API_BASE = "https://api.glassnode.com/v1"

# Cache keyed by (asset, metric_path, since, until, interval).
_cache: dict[tuple, tuple[datetime, dict[str, Any]]] = {}


def _reset_cache() -> None:
    """Test helper."""
    _cache.clear()


def _ensure_enabled() -> None:
    if not runtime_settings.get_bool_setting("GLASSNODE_ENABLED", default=False):
        raise RuntimeError(
            "GlassNode integration is disabled. Set GLASSNODE_ENABLED=true in settings to enable."
        )


def _api_base() -> str:
    base = (
        runtime_settings.get_setting("GLASSNODE_API_BASE", _DEFAULT_API_BASE)
        or _DEFAULT_API_BASE
    ).strip()
    return base.rstrip("/")


def _api_key() -> str:
    key = (runtime_settings.get_setting("GLASSNODE_API_KEY", "") or "").strip()
    if not key:
        raise RuntimeError(
            "GlassNode API key is missing. Set GLASSNODE_API_KEY in settings."
        )
    return key


async def _fetch_upstream(
    asset: str,
    metric_path: str,
    *,
    since: int | None,
    until: int | None,
    interval: str | None,
) -> list[dict]:
    base = _api_base()
    params: dict[str, Any] = {"a": asset, "api_key": _api_key()}
    if since is not None:
        params["s"] = since
    if until is not None:
        params["u"] = until
    if interval:
        params["i"] = interval
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.get(
            f"{base}/metrics/{metric_path}",
            params=params,
        )
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list):
        raise RuntimeError(
            f"GlassNode returned unexpected shape: {type(data).__name__}"
        )
    return data


def _obs_to_dict(obs: OnChainObservation) -> dict[str, Any]:
    return {"timestamp": obs.timestamp, "value": obs.value}


async def get_metric(
    asset: str,
    metric_path: str,
    *,
    since: int | None = None,
    until: int | None = None,
    interval: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch a GlassNode metric series with 5-min caching.

    Returns:
        {asset, metric_path, observations, generated_at, as_of}.
    Raises:
        RuntimeError when disabled or when key missing or when fetch fails
        with no cache to fall back to.
    """
    _ensure_enabled()

    key = (asset, metric_path, since, until, interval)
    now = datetime.now(timezone.utc)
    cached = _cache.get(key)

    if not force and cached is not None and now - cached[0] <= _CACHE_TTL:
        return cached[1]

    try:
        rows = await _fetch_upstream(
            asset,
            metric_path,
            since=since,
            until=until,
            interval=interval,
        )
        observations = parse_metric_payload(rows)
        payload = {
            "asset": asset.upper(),
            "metric_path": metric_path,
            "since": since,
            "until": until,
            "interval": interval,
            "observations": [_obs_to_dict(o) for o in observations],
            "generated_at": now,
            "as_of": now,
        }
        _cache[key] = (now, payload)
        return payload
    except Exception as exc:  # noqa: BLE001
        if cached is not None:
            logger.debug(
                "GlassNode fetch failed; serving stale cache (asset=%s metric=%s): %s",
                asset, metric_path, exc,
            )
            return cached[1]
        raise RuntimeError(f"GlassNode fetch failed: {exc}") from exc
