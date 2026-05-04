"""GlassNode adapter tests — pure compute + service with mocked httpx."""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

import pytest

from app.services import glassnode_service
from core.onchain import OnChainObservation, parse_metric_payload


# ---------- Pure compute ----------


def test_parse_metric_payload_basic():
    rows = [
        {"t": 1700000000, "v": 40000.0},
        {"t": 1700086400, "v": 40500.0},
    ]
    obs = parse_metric_payload(rows)
    assert len(obs) == 2
    assert obs[0].value == pytest.approx(40000.0)
    assert obs[0].timestamp.year == 2023


def test_parse_metric_payload_skips_non_dict():
    rows = [
        {"t": 1700000000, "v": 1.0},
        "not a dict",
        None,
        {"t": 1700086400, "v": 2.0},
    ]
    obs = parse_metric_payload(rows)
    assert len(obs) == 2


def test_parse_metric_payload_handles_null_value():
    rows = [{"t": 1700000000, "v": None}]
    obs = parse_metric_payload(rows)
    assert len(obs) == 1
    assert obs[0].value is None


def test_parse_metric_payload_skips_missing_timestamp():
    rows = [{"v": 100.0}]
    obs = parse_metric_payload(rows)
    assert obs == []


def test_parse_metric_payload_skips_non_numeric_value():
    rows = [{"t": 1700000000, "v": "not a number"}]
    obs = parse_metric_payload(rows)
    assert obs == []


def test_parse_metric_payload_sorts_ascending():
    rows = [
        {"t": 1700086400, "v": 2.0},
        {"t": 1700000000, "v": 1.0},
    ]
    obs = parse_metric_payload(rows)
    assert obs[0].value == pytest.approx(1.0)
    assert obs[1].value == pytest.approx(2.0)


# ---------- Service ----------


class GlassNodeServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        glassnode_service._reset_cache()  # noqa: SLF001
        # Default: gate off, key empty.
        self._gate = {"enabled": False, "key": ""}
        self._patch_settings = patch.multiple(
            glassnode_service.runtime_settings,
            get_bool_setting=self._fake_bool,
            get_setting=self._fake_get,
        )
        self._patch_settings.start()

    def tearDown(self) -> None:
        self._patch_settings.stop()

    def _fake_bool(self, key: str, default: bool = False) -> bool:
        if key == "GLASSNODE_ENABLED":
            return self._gate["enabled"]
        return default

    def _fake_get(self, key: str, default: Any = None) -> Any:
        if key == "GLASSNODE_API_KEY":
            return self._gate["key"]
        if key == "GLASSNODE_API_BASE":
            return default or "https://api.glassnode.com/v1"
        return default

    def _enable(self, key: str = "TEST_KEY") -> None:
        self._gate["enabled"] = True
        self._gate["key"] = key

    def _make_client(self, response_data: list[dict[str, Any]] | Exception):
        calls = {"n": 0, "url": None, "params": None}

        class _MockClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return None

            async def get(self, url: str, params: dict | None = None):
                calls["n"] += 1
                calls["url"] = url
                calls["params"] = params
                if isinstance(response_data, Exception):
                    raise response_data

                class _R:
                    status_code = 200

                    def raise_for_status(self) -> None:
                        return None

                    def json(self) -> Any:
                        return response_data

                return _R()

        return _MockClient, calls

    async def test_disabled_by_default_raises(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await glassnode_service.get_metric("BTC", "market/price_usd_close")

    async def test_enabled_with_key_fetches_metric(self) -> None:
        self._enable()
        klass, calls = self._make_client(
            [{"t": 1700000000, "v": 40000.0}, {"t": 1700086400, "v": 40500.0}]
        )
        with patch.object(glassnode_service.httpx, "AsyncClient", klass):
            payload = await glassnode_service.get_metric(
                "BTC", "market/price_usd_close"
            )
        self.assertEqual(payload["asset"], "BTC")
        self.assertEqual(payload["metric_path"], "market/price_usd_close")
        self.assertEqual(len(payload["observations"]), 2)
        self.assertIn("api_key", calls["params"])
        self.assertEqual(calls["params"]["api_key"], "TEST_KEY")
        self.assertEqual(calls["params"]["a"], "BTC")

    async def test_missing_key_raises_runtime_error(self) -> None:
        self._gate["enabled"] = True
        # Leave key empty.
        with self.assertRaisesRegex(RuntimeError, "key is missing"):
            await glassnode_service.get_metric("BTC", "market/price_usd_close")

    async def test_passes_optional_params(self) -> None:
        self._enable()
        klass, calls = self._make_client([])
        with patch.object(glassnode_service.httpx, "AsyncClient", klass):
            await glassnode_service.get_metric(
                "ETH",
                "addresses/active_count",
                since=1700000000,
                until=1700100000,
                interval="24h",
            )
        self.assertEqual(calls["params"]["s"], 1700000000)
        self.assertEqual(calls["params"]["u"], 1700100000)
        self.assertEqual(calls["params"]["i"], "24h")

    async def test_caches_within_ttl(self) -> None:
        self._enable()
        klass, calls = self._make_client([{"t": 1700000000, "v": 1.0}])
        with patch.object(glassnode_service.httpx, "AsyncClient", klass):
            await glassnode_service.get_metric("BTC", "market/price_usd_close")
            await glassnode_service.get_metric("BTC", "market/price_usd_close")
        self.assertEqual(calls["n"], 1)

    async def test_cache_keyed_by_full_tuple(self) -> None:
        """Different intervals should NOT share a cache slot."""
        self._enable()
        klass, calls = self._make_client([{"t": 1700000000, "v": 1.0}])
        with patch.object(glassnode_service.httpx, "AsyncClient", klass):
            await glassnode_service.get_metric(
                "BTC", "market/price_usd_close", interval="1h"
            )
            await glassnode_service.get_metric(
                "BTC", "market/price_usd_close", interval="24h"
            )
        self.assertEqual(calls["n"], 2)

    async def test_force_refresh_bypasses_cache(self) -> None:
        self._enable()
        klass, calls = self._make_client([{"t": 1700000000, "v": 1.0}])
        with patch.object(glassnode_service.httpx, "AsyncClient", klass):
            await glassnode_service.get_metric("BTC", "market/price_usd_close")
            await glassnode_service.get_metric(
                "BTC", "market/price_usd_close", force=True
            )
        self.assertEqual(calls["n"], 2)

    async def test_falls_back_to_cache_on_http_error(self) -> None:
        self._enable()
        # Phase 1: success populates cache.
        klass_ok, _ = self._make_client([{"t": 1700000000, "v": 1.0}])
        with patch.object(glassnode_service.httpx, "AsyncClient", klass_ok):
            first = await glassnode_service.get_metric(
                "BTC", "market/price_usd_close"
            )
        # Phase 2: failure → returns cached.
        klass_fail, _ = self._make_client(RuntimeError("network down"))
        with patch.object(glassnode_service.httpx, "AsyncClient", klass_fail):
            second = await glassnode_service.get_metric(
                "BTC", "market/price_usd_close", force=True
            )
        self.assertEqual(first["observations"], second["observations"])

    async def test_raises_when_no_cache_and_http_fails(self) -> None:
        self._enable()
        klass_fail, _ = self._make_client(RuntimeError("network down"))
        with patch.object(glassnode_service.httpx, "AsyncClient", klass_fail):
            with self.assertRaisesRegex(RuntimeError, "fetch failed"):
                await glassnode_service.get_metric(
                    "BTC", "market/price_usd_close"
                )


if __name__ == "__main__":
    unittest.main()
