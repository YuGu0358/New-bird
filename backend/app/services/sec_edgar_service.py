"""SEC EDGAR connector — recent filings, XBRL company concepts, filing text.

Pattern mirrors `glassnode_service` / `dbnomics_service`:
- Setting gate via `runtime_settings.get_bool_setting("SEC_EDGAR_ENABLED", default=True)`.
- Required `User-Agent` from `runtime_settings.get_setting("SEC_EDGAR_USER_AGENT", "")` —
  SEC will block requests without a contact-email UA. Fail fast if empty.
- Module-level TTL cache with stale-cache fallback on transient fetch error.
- 30-min TTL for filings/concept payloads; 24-hour TTL for the ticker→CIK map
  (rarely changes).
- Modest backoff on HTTP 429 (one retry), then bubble up.

Public async functions (each returns a dict with `as_of` + `generated_at`):
    get_recent_filings(symbol, form_types=("10-K","10-Q","8-K"), limit=20)
    get_company_concept(symbol, concept)
    get_filing_text(accession_number, *, max_chars=200_000)
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app import runtime_settings

logger = logging.getLogger(__name__)


_DATA_BASE = "https://data.sec.gov"
_WWW_BASE = "https://www.sec.gov"
_TICKER_MAP_URL = f"{_WWW_BASE}/files/company_tickers.json"

_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=4.0)
_DEFAULT_TTL = timedelta(minutes=30)
_TICKER_MAP_TTL = timedelta(hours=24)
_FILING_TEXT_DEFAULT_CHARS = 200_000
_RATE_LIMIT_BACKOFF_SECONDS = 0.5

_DEFAULT_FORM_TYPES: tuple[str, ...] = ("10-K", "10-Q", "8-K")

# Generic TTL cache keyed by tuple → (cached_at, payload).
_cache: dict[tuple, tuple[datetime, dict[str, Any]]] = {}

# Dedicated ticker→CIK map cache key.
_TICKER_MAP_KEY: tuple[str] = ("ticker_map",)


def _reset_cache() -> None:
    """Test helper — wipe all in-memory caches."""
    _cache.clear()


def _ensure_enabled() -> None:
    if not runtime_settings.get_bool_setting("SEC_EDGAR_ENABLED", default=True):
        raise RuntimeError(
            "SEC EDGAR integration is disabled. "
            "Set SEC_EDGAR_ENABLED=true in settings to enable."
        )


def _user_agent() -> str:
    raw = runtime_settings.get_setting("SEC_EDGAR_USER_AGENT", "") or ""
    value = raw.strip()
    if not value:
        raise RuntimeError(
            "SEC EDGAR requires a contact-email User-Agent. "
            "Set SEC_EDGAR_USER_AGENT in settings (e.g. 'Your Name you@example.com')."
        )
    return value


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": _user_agent(),
        "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
        "Accept-Encoding": "gzip, deflate",
    }


def _pad_cik(cik: str | int) -> str:
    digits = re.sub(r"\D", "", str(cik))
    if not digits:
        raise ValueError(f"Invalid CIK: {cik!r}")
    return digits.zfill(10)


# ----- ticker → CIK map -----


async def _fetch_ticker_map() -> dict[str, dict[str, Any]]:
    """Download SEC's master ticker list, normalized to `ticker → row`.

    Each upstream row has: cik_str (int), ticker (str), title (str). We re-key
    by upper-cased ticker for direct lookup.
    """
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.get(_TICKER_MAP_URL, headers=_default_headers())
        response.raise_for_status()
        body = response.json()

    if not isinstance(body, dict):
        raise RuntimeError("SEC EDGAR ticker map: unexpected payload shape")

    out: dict[str, dict[str, Any]] = {}
    for row in body.values():
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        out[ticker] = {
            "cik_str": row.get("cik_str"),
            "ticker": ticker,
            "title": row.get("title"),
        }
    return out


async def _get_ticker_map(*, force: bool = False) -> dict[str, dict[str, Any]]:
    now = datetime.now(timezone.utc)
    cached = _cache.get(_TICKER_MAP_KEY)
    if not force and cached is not None and now - cached[0] <= _TICKER_MAP_TTL:
        return cached[1]["mapping"]

    try:
        mapping = await _fetch_ticker_map()
    except Exception as exc:  # noqa: BLE001 — surface any transport-level error.
        if cached is not None:
            logger.debug(
                "SEC EDGAR ticker map fetch failed; serving stale cache: %s", exc
            )
            return cached[1]["mapping"]
        raise RuntimeError(f"SEC EDGAR ticker map fetch failed: {exc}") from exc

    _cache[_TICKER_MAP_KEY] = (now, {"mapping": mapping})
    return mapping


async def _resolve_cik(symbol: str) -> str:
    """Return the 10-digit padded CIK for `symbol` (raises LookupError if unknown)."""
    ticker = symbol.strip().upper()
    if not ticker:
        raise ValueError("symbol must be a non-empty ticker")
    mapping = await _get_ticker_map()
    row = mapping.get(ticker)
    if row is None:
        raise LookupError(f"SEC EDGAR has no CIK on file for ticker {ticker!r}")
    return _pad_cik(row["cik_str"])


# ----- HTTP helper with one-shot 429 backoff -----


async def _http_get(url: str, *, accept_html: bool = False) -> httpx.Response:
    """One GET with a single retry on HTTP 429.

    Caller decides what to do with the final status code. We only handle 429
    here so each caller's error path stays simple and uniform.
    """
    headers = _default_headers()
    if accept_html:
        headers["Accept"] = "text/html, application/xhtml+xml, */*;q=0.9"

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.get(url, headers=headers)
        if response.status_code == 429:
            await asyncio.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
            response = await client.get(url, headers=headers)
        return response


# ----- recent filings -----


def _filter_filings(
    filings_block: dict[str, Any],
    *,
    form_types: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    """Project the SEC `submissions` recent-filings block into our row shape."""
    recent = filings_block.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []

    accession_numbers = recent.get("accessionNumber") or []
    forms = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    primary_documents = recent.get("primaryDocument") or []
    items_field = recent.get("items") or []
    report_dates = recent.get("reportDate") or []
    cik = filings_block.get("cik") or ""

    wanted = {form.upper() for form in form_types}
    out: list[dict[str, Any]] = []
    for idx, form in enumerate(forms):
        if not isinstance(form, str) or form.upper() not in wanted:
            continue
        accession = accession_numbers[idx] if idx < len(accession_numbers) else ""
        if not accession:
            continue
        primary_doc = (
            primary_documents[idx] if idx < len(primary_documents) else ""
        )
        accession_no_dashes = accession.replace("-", "")
        primary_doc_url = (
            f"{_WWW_BASE}/Archives/edgar/data/{int(cik)}/{accession_no_dashes}/{primary_doc}"
            if primary_doc and cik
            else ""
        )
        out.append(
            {
                "accession_number": accession,
                "form_type": form,
                "filing_date": filing_dates[idx] if idx < len(filing_dates) else "",
                "primary_document": primary_doc,
                "primary_doc_url": primary_doc_url,
                "items": items_field[idx] if idx < len(items_field) else "",
                "report_date": report_dates[idx] if idx < len(report_dates) else "",
            }
        )
        if len(out) >= limit:
            break
    return out


async def _fetch_submissions(cik_padded: str) -> dict[str, Any]:
    url = f"{_DATA_BASE}/submissions/CIK{cik_padded}.json"
    response = await _http_get(url)
    if response.status_code == 404:
        raise LookupError(f"SEC EDGAR submissions not found for CIK {cik_padded}")
    if response.status_code >= 400:
        raise RuntimeError(
            f"SEC EDGAR submissions HTTP {response.status_code} for CIK {cik_padded}"
        )
    body = response.json()
    if not isinstance(body, dict):
        raise RuntimeError("SEC EDGAR submissions: unexpected payload shape")
    return body


async def get_recent_filings(
    symbol: str,
    form_types: tuple[str, ...] = _DEFAULT_FORM_TYPES,
    limit: int = 20,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch a normalized list of recent filings for `symbol`.

    Returns:
        {symbol, cik, form_types, limit, filings, as_of, generated_at}.
    """
    _ensure_enabled()
    if limit <= 0:
        raise ValueError("limit must be positive")
    normalized_forms = tuple(sorted({f.upper() for f in form_types if f}))
    if not normalized_forms:
        raise ValueError("form_types must contain at least one form")

    ticker = symbol.strip().upper()
    cache_key = ("recent_filings", ticker, normalized_forms, limit)
    now = datetime.now(timezone.utc)
    cached = _cache.get(cache_key)
    cache_is_fresh = cached is not None and now - cached[0] <= _DEFAULT_TTL
    if not force and cache_is_fresh:
        return _with_generated_at(cached[1])

    try:
        cik_padded = await _resolve_cik(ticker)
        body = await _fetch_submissions(cik_padded)
        filings = _filter_filings(body, form_types=normalized_forms, limit=limit)
        payload = {
            "symbol": ticker,
            "cik": cik_padded,
            "form_types": list(normalized_forms),
            "limit": limit,
            "filings": filings,
            "as_of": now,
        }
    except LookupError:
        raise
    except Exception as exc:  # noqa: BLE001
        if cached is not None:
            logger.debug(
                "SEC EDGAR get_recent_filings failed; serving stale cache (symbol=%s): %s",
                ticker,
                exc,
            )
            return _with_generated_at(cached[1])
        raise RuntimeError(f"SEC EDGAR get_recent_filings failed: {exc}") from exc

    _cache[cache_key] = (now, payload)
    return _with_generated_at(payload)


# ----- XBRL company concept -----


async def get_company_concept(
    symbol: str,
    concept: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch a single us-gaap XBRL concept (e.g. 'Revenues', 'EarningsPerShareDiluted')."""
    _ensure_enabled()
    ticker = symbol.strip().upper()
    concept_clean = concept.strip()
    if not concept_clean:
        raise ValueError("concept must be a non-empty XBRL tag")

    cache_key = ("company_concept", ticker, concept_clean)
    now = datetime.now(timezone.utc)
    cached = _cache.get(cache_key)
    if not force and cached is not None and now - cached[0] <= _DEFAULT_TTL:
        return _with_generated_at(cached[1])

    try:
        cik_padded = await _resolve_cik(ticker)
        url = (
            f"{_DATA_BASE}/api/xbrl/companyconcept/CIK{cik_padded}"
            f"/us-gaap/{concept_clean}.json"
        )
        response = await _http_get(url)
        if response.status_code == 404:
            raise LookupError(
                f"SEC EDGAR has no us-gaap/{concept_clean} for {ticker} (CIK {cik_padded})"
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"SEC EDGAR companyconcept HTTP {response.status_code} for {ticker}"
            )
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("SEC EDGAR companyconcept: unexpected payload shape")
        payload = {
            "symbol": ticker,
            "cik": cik_padded,
            "concept": concept_clean,
            "data": body,
            "as_of": now,
        }
    except LookupError:
        raise
    except Exception as exc:  # noqa: BLE001
        if cached is not None:
            logger.debug(
                "SEC EDGAR get_company_concept failed; serving stale cache "
                "(symbol=%s concept=%s): %s",
                ticker,
                concept_clean,
                exc,
            )
            return _with_generated_at(cached[1])
        raise RuntimeError(f"SEC EDGAR get_company_concept failed: {exc}") from exc

    _cache[cache_key] = (now, payload)
    return _with_generated_at(payload)


# ----- filing text -----


_ACCESSION_RE = re.compile(r"^(\d{10})-(\d{2})-(\d{6})$")


def _parse_accession(accession_number: str) -> tuple[str, str]:
    """Return (cik_int_no_pad, accession_no_dashes) from `nnnnnnnnnn-nn-nnnnnn`."""
    match = _ACCESSION_RE.match(accession_number.strip())
    if not match:
        raise ValueError(
            f"Invalid accession number {accession_number!r}; "
            "expected 'nnnnnnnnnn-nn-nnnnnn'"
        )
    cik_no_pad = str(int(match.group(1)))
    no_dashes = accession_number.replace("-", "")
    return cik_no_pad, no_dashes


async def get_filing_text(
    accession_number: str,
    *,
    max_chars: int = _FILING_TEXT_DEFAULT_CHARS,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch the index page for a filing and return a trimmed text snapshot.

    SEC filings contain many documents per accession; we return the index HTML
    text trimmed to `max_chars`. Heavier extraction (primary-document parse)
    is deferred to higher layers.
    """
    _ensure_enabled()
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    cik_no_pad, no_dashes = _parse_accession(accession_number)

    cache_key = ("filing_text", accession_number, max_chars)
    now = datetime.now(timezone.utc)
    cached = _cache.get(cache_key)
    if not force and cached is not None and now - cached[0] <= _DEFAULT_TTL:
        return _with_generated_at(cached[1])

    try:
        browse_url = (
            f"{_WWW_BASE}/cgi-bin/browse-edgar"
            f"?action=getcompany&CIK={cik_no_pad}&type=&dateb=&owner=include&count=40"
        )
        index_url = (
            f"{_WWW_BASE}/Archives/edgar/data/{cik_no_pad}/{no_dashes}/"
            f"{accession_number}-index.htm"
        )
        response = await _http_get(index_url, accept_html=True)
        if response.status_code == 404:
            raise LookupError(
                f"SEC EDGAR filing index not found: {accession_number}"
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"SEC EDGAR filing-text HTTP {response.status_code} "
                f"for {accession_number}"
            )
        text = response.text or ""
        truncated = text[:max_chars]
        payload = {
            "accession_number": accession_number,
            "cik": cik_no_pad,
            "index_url": index_url,
            "browse_url": browse_url,
            "max_chars": max_chars,
            "truncated": len(text) > max_chars,
            "text": truncated,
            "as_of": now,
        }
    except LookupError:
        raise
    except Exception as exc:  # noqa: BLE001
        if cached is not None:
            logger.debug(
                "SEC EDGAR get_filing_text failed; serving stale cache "
                "(accession=%s): %s",
                accession_number,
                exc,
            )
            return _with_generated_at(cached[1])
        raise RuntimeError(f"SEC EDGAR get_filing_text failed: {exc}") from exc

    _cache[cache_key] = (now, payload)
    return _with_generated_at(payload)


# ----- shared helpers -----


def _with_generated_at(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with a fresh `generated_at` timestamp."""
    return {**payload, "generated_at": datetime.now(timezone.utc)}
