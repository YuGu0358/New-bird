"""Kraken broker + service tests (mocked httpx)."""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from app.services import kraken_service
from core.broker import kraken as kraken_broker


class _MockResponse:
    def __init__(self, status_code: int, json_data: Any) -> None:
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise kraken_broker.httpx.HTTPStatusError(
                "boom", request=None, response=None  # type: ignore[arg-type]
            )

    def json(self) -> Any:
        return self._json


def _client_factory(response: _MockResponse | Exception):
    """Build a context-manager-shaped fake httpx.AsyncClient."""

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, params: dict | None = None):
            if isinstance(response, Exception):
                raise response
            return response

    return _Client


class KrakenBrokerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        kraken_service._reset_cache()  # noqa: SLF001
        # Default: gate ON for these tests (we test gate-off separately).
        self._patches = [
            patch.object(
                kraken_broker.runtime_settings,
                "get_bool_setting",
                lambda key, default=False: True if key == "KRAKEN_ENABLED" else default,
            ),
            patch.object(
                kraken_broker.runtime_settings,
                "get_setting",
                lambda key, default=None: (
                    "https://api.kraken.com"
                    if key == "KRAKEN_API_BASE"
                    else default
                ),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    # ---------- gate ----------

    async def test_disabled_raises(self) -> None:
        with patch.object(
            kraken_broker.runtime_settings,
            "get_bool_setting",
            lambda *_, **__: False,
        ):
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                await kraken_broker.fetch_ticker("XBTUSD")

    # ---------- ticker happy path ----------

    async def test_fetch_ticker_returns_result(self) -> None:
        body = {
            "error": [],
            "result": {
                "XXBTZUSD": {"a": ["67000.0", "1", "1.000"], "b": ["66950.0", "1", "1.000"]}
            },
        }
        with patch.object(
            kraken_broker.httpx,
            "AsyncClient",
            _client_factory(_MockResponse(200, body)),
        ):
            result = await kraken_broker.fetch_ticker("XBTUSD")
        self.assertIn("XXBTZUSD", result)

    # ---------- recent trades happy path ----------

    async def test_fetch_recent_trades_returns_result(self) -> None:
        body = {
            "error": [],
            "result": {
                "XXBTZUSD": [["67000.0", "0.01", 1700000000.0, "b", "m", ""]],
                "last": "1700000000000000000",
            },
        }
        with patch.object(
            kraken_broker.httpx,
            "AsyncClient",
            _client_factory(_MockResponse(200, body)),
        ):
            result = await kraken_broker.fetch_recent_trades("XBTUSD")
        self.assertIn("XXBTZUSD", result)
        self.assertIn("last", result)

    # ---------- asset pair listing ----------

    async def test_fetch_asset_pairs_returns_result(self) -> None:
        body = {
            "error": [],
            "result": {
                "XXBTZUSD": {"altname": "XBTUSD", "wsname": "XBT/USD"},
                "XETHZUSD": {"altname": "ETHUSD", "wsname": "ETH/USD"},
            },
        }
        with patch.object(
            kraken_broker.httpx,
            "AsyncClient",
            _client_factory(_MockResponse(200, body)),
        ):
            result = await kraken_broker.fetch_asset_pairs()
        self.assertIn("XXBTZUSD", result)
        self.assertIn("XETHZUSD", result)

    # ---------- error envelope ----------

    async def test_error_envelope_raises_kraken_api_error(self) -> None:
        body = {"error": ["EQuery:Unknown asset pair"], "result": {}}
        with patch.object(
            kraken_broker.httpx,
            "AsyncClient",
            _client_factory(_MockResponse(200, body)),
        ):
            with self.assertRaises(kraken_broker.KrakenAPIError):
                await kraken_broker.fetch_ticker("UNKNOWN")

    # ---------- network failure ----------

    async def test_network_error_propagates(self) -> None:
        with patch.object(
            kraken_broker.httpx,
            "AsyncClient",
            _client_factory(RuntimeError("network down")),
        ):
            with self.assertRaisesRegex(RuntimeError, "network down"):
                await kraken_broker.fetch_ticker("XBTUSD")

    # ---------- timeout config ----------

    def test_request_timeout_is_five_seconds(self) -> None:
        # Read-out check — 5s read, 2s connect per the quality bar.
        timeout = kraken_broker._REQUEST_TIMEOUT  # noqa: SLF001
        self.assertEqual(timeout.read, 5.0)
        self.assertEqual(timeout.connect, 2.0)

    # ---------- service-layer cache ----------

    async def test_service_caches_ticker_within_ttl(self) -> None:
        body = {"error": [], "result": {"XXBTZUSD": {"a": ["1"]}}}
        call_count = {"n": 0}

        class _CountedClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None: pass
            async def __aenter__(self) -> "_CountedClient": return self
            async def __aexit__(self, *args: Any) -> None: return None
            async def get(self, url: str, params: dict | None = None):
                call_count["n"] += 1
                return _MockResponse(200, body)

        with patch.object(kraken_broker.httpx, "AsyncClient", _CountedClient):
            await kraken_service.get_ticker("XBTUSD")
            await kraken_service.get_ticker("XBTUSD")
        self.assertEqual(call_count["n"], 1)

    async def test_service_force_refresh_bypasses_cache(self) -> None:
        body = {"error": [], "result": {}}
        call_count = {"n": 0}

        class _CountedClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None: pass
            async def __aenter__(self) -> "_CountedClient": return self
            async def __aexit__(self, *args: Any) -> None: return None
            async def get(self, url: str, params: dict | None = None):
                call_count["n"] += 1
                return _MockResponse(200, body)

        with patch.object(kraken_broker.httpx, "AsyncClient", _CountedClient):
            await kraken_service.get_ticker("XBTUSD")
            await kraken_service.get_ticker("XBTUSD", force=True)
        self.assertEqual(call_count["n"], 2)

    # ---------- broker contract — paper/read-only ----------

    async def test_broker_list_positions_returns_empty(self) -> None:
        broker = kraken_broker.KrakenBroker()
        self.assertEqual(await broker.list_positions(), [])

    async def test_broker_list_orders_returns_empty(self) -> None:
        broker = kraken_broker.KrakenBroker()
        self.assertEqual(await broker.list_orders(), [])

    async def test_broker_submit_order_raises_not_implemented(self) -> None:
        broker = kraken_broker.KrakenBroker()
        with self.assertRaises(NotImplementedError):
            await broker.submit_order(symbol="XBTUSD", side="buy", notional=10.0)

    async def test_broker_close_position_raises_not_implemented(self) -> None:
        broker = kraken_broker.KrakenBroker()
        with self.assertRaises(NotImplementedError):
            await broker.close_position("XBTUSD")

    async def test_broker_account_returns_read_only_stub(self) -> None:
        broker = kraken_broker.KrakenBroker()
        account = await broker.get_account()
        self.assertEqual(account["status"], "READ_ONLY")
        self.assertEqual(account["equity"], 0.0)
