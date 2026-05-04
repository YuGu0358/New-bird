"""DBnomics adapter — fetch a single (provider, dataset, series_id) time series.

DBnomics is a public good (no key, no opt-in), so unlike CoinGecko there is
no setting gate. The only knobs are timeout (hardcoded) and cache TTL
(30 minutes — DBnomics data is monthly/quarterly so a long TTL is fine).

Failure modes:
- 4xx with status 404 -> `LookupError` (router maps to 404).
- 4xx other than 404  -> `RuntimeError` with the upstream status.
- 5xx OR network failure AND cache populated -> serve cached payload (DEBUG).
- 5xx OR network failure AND cache empty     -> `RuntimeError`.
- payload missing `series.docs[0]` (or empty docs) -> `LookupError`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from core.dbnomics import DBnomicsSeries, parse_series_doc

logger = logging.getLogger(__name__)


_API_BASE = "https://api.db.nomics.world/v22"
_CACHE_TTL = timedelta(minutes=30)
_TIMEOUT = httpx.Timeout(10.0, connect=4.0)


# Cache keyed by (provider, dataset, series_id) -> (cached_at, payload).
_cache: dict[tuple[str, str, str], tuple[datetime, dict[str, Any]]] = {}


def _reset_cache() -> None:
    """Test helper — wipe the in-memory cache."""
    _cache.clear()


def _series_to_payload(
    series: DBnomicsSeries,
    *,
    as_of: datetime,
) -> dict[str, Any]:
    """Translate the dataclass into the dict shape returned by the service."""
    return {
        "provider_code": series.provider_code,
        "dataset_code": series.dataset_code,
        "series_code": series.series_code,
        "series_name": series.series_name,
        "frequency": series.frequency,
        "indexed_at": series.indexed_at,
        "observations": [
            {
                "period": obs.period,
                "date": obs.date,
                "value": obs.value,
            }
            for obs in series.observations
        ],
        "as_of": as_of,
    }


async def _fetch_upstream(
    provider: str,
    dataset: str,
    series_id: str,
) -> dict[str, Any]:
    """One async GET against DBnomics.

    Returns the parsed payload dict (without `generated_at`). Raises
    `LookupError` for 404 / empty docs, `RuntimeError` for other HTTP
    errors, and lets transport-level exceptions bubble up so the caller
    can decide between cache fallback and re-raise.
    """
    url = (
        f"{_API_BASE}/series/{provider}/{dataset}/{series_id}"
        f"?observations=1"
    )

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(url)
        status = response.status_code

        if status == 404:
            raise LookupError(
                f"DBnomics series not found: {provider}/{dataset}/{series_id}"
            )
        if 400 <= status < 500:
            raise RuntimeError(
                f"DBnomics returned HTTP {status} for "
                f"{provider}/{dataset}/{series_id}"
            )
        if status >= 500:
            # 5xx is treated like a transport failure so the outer cache-
            # fallback path can kick in.
            raise RuntimeError(
                f"DBnomics upstream HTTP {status} for "
                f"{provider}/{dataset}/{series_id}"
            )

        body = response.json()

    if not isinstance(body, dict):
        raise RuntimeError("DBnomics returned a non-object payload")

    series_block = body.get("series") or {}
    docs = series_block.get("docs") if isinstance(series_block, dict) else None
    if not isinstance(docs, list) or not docs:
        raise LookupError(
            f"DBnomics returned no series for "
            f"{provider}/{dataset}/{series_id}"
        )

    parsed = parse_series_doc(docs[0])
    if parsed is None:
        raise RuntimeError(
            f"DBnomics returned an unparseable series document for "
            f"{provider}/{dataset}/{series_id}"
        )

    return _series_to_payload(parsed, as_of=datetime.now(timezone.utc))


async def get_series(
    provider: str,
    dataset: str,
    series_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Return a normalized DBnomics series payload (dict-shaped).

    Cache-fresh path returns immediately. On a stale or missing cache slot
    we fetch upstream; transient failures (5xx / network) silently fall
    back to any cached payload, otherwise propagate as `RuntimeError`.
    """
    key = (provider, dataset, series_id)
    now = datetime.now(timezone.utc)

    cached = _cache.get(key)
    cache_is_fresh = cached is not None and now - cached[0] <= _CACHE_TTL

    if not force and cache_is_fresh:
        payload = cached[1]
    else:
        try:
            payload = await _fetch_upstream(provider, dataset, series_id)
        except LookupError:
            # Definitive "not there" — never serve stale.
            raise
        except RuntimeError as exc:
            # Includes 4xx-other-than-404 and 5xx. For 5xx we'd ideally
            # fall back to cache; we treat any RuntimeError that came out
            # of upstream the same way the CoinGecko service does.
            if cached is not None:
                logger.debug(
                    "DBnomics fetch failed; serving stale cache (%s): %s",
                    key,
                    exc,
                )
                payload = cached[1]
            else:
                raise
        except Exception as exc:
            # Transport-level exception (httpx.RequestError, timeout, etc).
            if cached is not None:
                logger.debug(
                    "DBnomics fetch raised; serving stale cache (%s): %s",
                    key,
                    exc,
                )
                payload = cached[1]
            else:
                raise RuntimeError(
                    f"DBnomics fetch failed and no cache is available: {exc}"
                ) from exc
        else:
            _cache[key] = (now, payload)

    return {
        **payload,
        "generated_at": datetime.now(timezone.utc),
    }
