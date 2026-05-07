"""SEC EDGAR connector tests — gating, caching, stale-cache fallback.

Mirrors `test_glassnode_service.py` style: `unittest.IsolatedAsyncioTestCase`
with `unittest.mock.patch` to swap `httpx.AsyncClient` and the
`runtime_settings` getters. CI runs `python -m unittest discover -s tests`,
so we deliberately avoid pytest-only fixtures here.
"""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from app.services import sec_edgar_service


# ----- synthetic fixtures (NOT real SEC data) -----


_TICKER_MAP_PAYLOAD: dict[str, dict[str, Any]] = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}


_SUBMISSIONS_PAYLOAD: dict[str, Any] = {
    "cik": "320193",
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-25-000001",
                "0000320193-24-000099",
                "0000320193-24-000050",
            ],
            "form": ["10-K", "8-K", "10-Q"],
            "filingDate": ["2025-10-30", "2025-08-01", "2025-07-25"],
            "primaryDocument": [
                "aapl-20250930.htm",
                "ex991.htm",
                "aapl-20250628.htm",
            ],
            "items": ["", "2.02,9.01", ""],
            "reportDate": ["2025-09-30", "2025-08-01", "2025-06-28"],
        }
    },
}


class _MockResponse:
    """Lightweight stand-in for httpx.Response."""

    def __init__(
        self,
        json_payload: Any | None = None,
        *,
        status_code: int = 200,
        text: str = "",
    ) -> None:
        self._json = json_payload
        self.status_code = status_code
        self.text = text

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _make_async_client(handler):
    """Build a fake `httpx.AsyncClient` whose `.get(url, **kwargs)` calls `handler`."""

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, **kwargs: Any):
            return handler(url, **kwargs)

    return _Client


# ----- test cases -----


class SecEdgarServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        sec_edgar_service._reset_cache()  # noqa: SLF001
        self._gate = {"enabled": True, "user_agent": "Tester test@example.com"}
        self._patch_settings = patch.multiple(
            sec_edgar_service.runtime_settings,
            get_bool_setting=self._fake_bool,
            get_setting=self._fake_get,
        )
        self._patch_settings.start()

    def tearDown(self) -> None:
        self._patch_settings.stop()
        sec_edgar_service._reset_cache()  # noqa: SLF001

    # ---- gate fakes ----

    def _fake_bool(self, key: str, default: bool = False) -> bool:
        if key == "SEC_EDGAR_ENABLED":
            return self._gate["enabled"]
        return default

    def _fake_get(self, key: str, default: Any = None) -> Any:
        if key == "SEC_EDGAR_USER_AGENT":
            return self._gate["user_agent"]
        return default

    # ---- 1. missing User-Agent fails fast ----

    async def test_missing_user_agent_raises_runtime_error(self) -> None:
        self._gate["user_agent"] = ""

        def handler(url: str, **kwargs: Any) -> _MockResponse:
            return _MockResponse(_TICKER_MAP_PAYLOAD)

        with patch.object(
            sec_edgar_service.httpx, "AsyncClient", _make_async_client(handler)
        ):
            with self.assertRaisesRegex(RuntimeError, "User-Agent"):
                await sec_edgar_service.get_recent_filings("AAPL")

    # ---- 2. disabled gate raises ----

    async def test_disabled_gate_raises(self) -> None:
        self._gate["enabled"] = False
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await sec_edgar_service.get_recent_filings("AAPL")

    # ---- 3. cache hit returns cached payload, no HTTP ----

    async def test_cache_hit_skips_http(self) -> None:
        calls = {"n": 0}

        def handler(url: str, **kwargs: Any) -> _MockResponse:
            calls["n"] += 1
            if "company_tickers.json" in url:
                return _MockResponse(_TICKER_MAP_PAYLOAD)
            if "submissions/CIK" in url:
                return _MockResponse(_SUBMISSIONS_PAYLOAD)
            return _MockResponse({}, status_code=404)

        with patch.object(
            sec_edgar_service.httpx, "AsyncClient", _make_async_client(handler)
        ):
            first = await sec_edgar_service.get_recent_filings("AAPL")
            calls_after_first = calls["n"]
            second = await sec_edgar_service.get_recent_filings("AAPL")

        # First call: 1 ticker-map fetch + 1 submissions fetch = 2.
        # Second call: cache hit, no extra HTTP.
        self.assertEqual(calls_after_first, 2)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(first["filings"], second["filings"])
        self.assertEqual(first["symbol"], "AAPL")
        self.assertEqual(first["cik"], "0000320193")

    # ---- 4. cache miss + fetch success populates cache ----

    async def test_cache_populated_on_success(self) -> None:
        def handler(url: str, **kwargs: Any) -> _MockResponse:
            if "company_tickers.json" in url:
                return _MockResponse(_TICKER_MAP_PAYLOAD)
            if "submissions/CIK" in url:
                return _MockResponse(_SUBMISSIONS_PAYLOAD)
            return _MockResponse({}, status_code=404)

        with patch.object(
            sec_edgar_service.httpx, "AsyncClient", _make_async_client(handler)
        ):
            payload = await sec_edgar_service.get_recent_filings(
                "AAPL", form_types=("10-K", "10-Q", "8-K"), limit=10
            )

        self.assertEqual(len(payload["filings"]), 3)
        forms = {row["form_type"] for row in payload["filings"]}
        self.assertEqual(forms, {"10-K", "10-Q", "8-K"})
        first_filing = payload["filings"][0]
        self.assertIn("primary_doc_url", first_filing)
        self.assertTrue(
            first_filing["primary_doc_url"].startswith("https://www.sec.gov/")
        )
        self.assertIn("as_of", payload)
        self.assertIn("generated_at", payload)

        # Verify the cache slot is now populated (4-tuple key for the
        # normalized form_types and limit).
        normalized = tuple(sorted({"10-K", "10-Q", "8-K"}))
        cache_key = ("recent_filings", "AAPL", normalized, 10)
        self.assertIn(cache_key, sec_edgar_service._cache)  # noqa: SLF001

    # ---- 5. cache miss + fetch error + stale cache → returns stale ----

    async def test_stale_cache_fallback_on_fetch_error(self) -> None:
        # Phase 1: success populates cache.
        def ok_handler(url: str, **kwargs: Any) -> _MockResponse:
            if "company_tickers.json" in url:
                return _MockResponse(_TICKER_MAP_PAYLOAD)
            if "submissions/CIK" in url:
                return _MockResponse(_SUBMISSIONS_PAYLOAD)
            return _MockResponse({}, status_code=404)

        with patch.object(
            sec_edgar_service.httpx, "AsyncClient", _make_async_client(ok_handler)
        ):
            first = await sec_edgar_service.get_recent_filings("AAPL")

        # Phase 2: failure on a forced refresh — cache fallback should kick in.
        def fail_handler(url: str, **kwargs: Any) -> _MockResponse:
            raise RuntimeError("upstream down")

        with patch.object(
            sec_edgar_service.httpx, "AsyncClient", _make_async_client(fail_handler)
        ):
            second = await sec_edgar_service.get_recent_filings("AAPL", force=True)

        self.assertEqual(first["filings"], second["filings"])
        self.assertEqual(second["symbol"], "AAPL")

    # ---- 6. CIK lookup caches the ticker map ----

    async def test_ticker_map_is_cached(self) -> None:
        ticker_calls = {"n": 0}

        def handler(url: str, **kwargs: Any) -> _MockResponse:
            if "company_tickers.json" in url:
                ticker_calls["n"] += 1
                return _MockResponse(_TICKER_MAP_PAYLOAD)
            if "submissions/CIK" in url:
                return _MockResponse(_SUBMISSIONS_PAYLOAD)
            return _MockResponse({}, status_code=404)

        with patch.object(
            sec_edgar_service.httpx, "AsyncClient", _make_async_client(handler)
        ):
            await sec_edgar_service.get_recent_filings("AAPL")
            # Different cache slot for the second call (different limit) so
            # _resolve_cik runs again — the ticker map should still be cached.
            await sec_edgar_service.get_recent_filings("AAPL", limit=5)

        self.assertEqual(ticker_calls["n"], 1)

    # ---- 7. unknown ticker raises LookupError ----

    async def test_unknown_ticker_raises_lookup_error(self) -> None:
        def handler(url: str, **kwargs: Any) -> _MockResponse:
            if "company_tickers.json" in url:
                return _MockResponse(_TICKER_MAP_PAYLOAD)
            return _MockResponse({}, status_code=404)

        with patch.object(
            sec_edgar_service.httpx, "AsyncClient", _make_async_client(handler)
        ):
            with self.assertRaisesRegex(LookupError, "no CIK"):
                await sec_edgar_service.get_recent_filings("ZZZZ")

    # ---- 8. fetch error with NO cache → RuntimeError ----

    async def test_no_cache_and_fetch_error_raises(self) -> None:
        def handler(url: str, **kwargs: Any) -> _MockResponse:
            if "company_tickers.json" in url:
                return _MockResponse(_TICKER_MAP_PAYLOAD)
            raise RuntimeError("submissions down")

        with patch.object(
            sec_edgar_service.httpx, "AsyncClient", _make_async_client(handler)
        ):
            with self.assertRaisesRegex(RuntimeError, "get_recent_filings failed"):
                await sec_edgar_service.get_recent_filings("AAPL")

    # ---- 9. invalid accession number rejected ----

    async def test_get_filing_text_rejects_bad_accession(self) -> None:
        with self.assertRaisesRegex(ValueError, "accession number"):
            await sec_edgar_service.get_filing_text("not-an-accession")


if __name__ == "__main__":
    unittest.main()
