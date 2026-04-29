"""Polymarket adapter tests — pure compute + service with mocked httpx."""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

import pytest

from app.services import polymarket_service
from core.predictions import (
    PredictionMarket,
    PredictionOutcome,
    parse_markets_payload,
    sort_and_limit,
)
from core.predictions.compute import SORTABLE_COLUMNS


# ---------- Pure compute ----------


def _market_dict(
    *,
    market_id: str = "0x1",
    question: str = "Will X happen?",
    outcomes: str = '["Yes","No"]',
    prices: str = '["0.62","0.38"]',
    volume: float = 1_000_000.0,
    liquidity: float = 50_000.0,
    end_date: str = "2026-12-31T23:59:59Z",
) -> dict[str, Any]:
    return {
        "id": market_id,
        "question": question,
        "slug": "x-happens",
        "category": "Politics",
        "endDate": end_date,
        "active": True,
        "closed": False,
        "outcomes": outcomes,
        "outcomePrices": prices,
        "volumeNum": volume,
        "liquidityNum": liquidity,
    }


def test_parse_markets_payload_normalizes_basic_market():
    rows = parse_markets_payload([_market_dict()])
    assert len(rows) == 1
    m = rows[0]
    assert m.id == "0x1"
    assert m.question == "Will X happen?"
    assert m.yes_price == pytest.approx(0.62)
    assert len(m.outcomes) == 2
    assert m.outcomes[0].label == "Yes"
    assert m.outcomes[0].price == pytest.approx(0.62)
    assert m.outcomes[1].label == "No"
    assert m.outcomes[1].price == pytest.approx(0.38)
    assert m.volume_usd == 1_000_000.0
    assert m.liquidity_usd == 50_000.0
    assert m.end_date == "2026-12-31T23:59:59Z"


def test_parse_markets_payload_skips_malformed_rows():
    """Items without id or question are dropped."""
    rows = parse_markets_payload(
        [
            _market_dict(market_id="ok-1"),
            {"question": "no id"},
            {"id": "no-question"},
            "not a dict",
            None,
            _market_dict(market_id="ok-2"),
        ]
    )
    ids = [r.id for r in rows]
    assert ids == ["ok-1", "ok-2"]


def test_parse_markets_payload_handles_already_decoded_outcomes():
    """If upstream returns lists instead of JSON strings, we still parse."""
    rows = parse_markets_payload(
        [
            _market_dict(
                outcomes=["Yes", "No"],  # type: ignore[arg-type]
                prices=[0.55, 0.45],  # type: ignore[arg-type]
            )
        ]
    )
    assert len(rows) == 1
    assert rows[0].yes_price == pytest.approx(0.55)


def test_parse_markets_payload_handles_missing_outcome_prices():
    """Outcomes present but prices empty → outcomes still listed with price=None."""
    rows = parse_markets_payload([_market_dict(prices="[]")])
    assert len(rows) == 1
    assert rows[0].outcomes[0].price is None
    assert rows[0].outcomes[1].price is None
    assert rows[0].yes_price is None


def test_parse_markets_payload_yes_price_only_when_first_outcome_is_yes():
    """A multi-candidate market doesn't get a yes_price."""
    rows = parse_markets_payload(
        [_market_dict(outcomes='["Trump","Biden","Other"]', prices='["0.5","0.4","0.1"]')]
    )
    assert len(rows) == 1
    assert rows[0].yes_price is None


def test_sort_and_limit_volume_desc_default():
    rows = [
        PredictionMarket(id="a", question="q", volume_usd=100.0),
        PredictionMarket(id="b", question="q", volume_usd=300.0),
        PredictionMarket(id="c", question="q", volume_usd=None),  # → last
        PredictionMarket(id="d", question="q", volume_usd=200.0),
    ]
    out = sort_and_limit(rows)
    assert [r.id for r in out] == ["b", "d", "a", "c"]


def test_sort_and_limit_unknown_sort_by_raises_value_error():
    with pytest.raises(ValueError, match="sort_by must be one of"):
        sort_and_limit([], sort_by="nonsense")


def test_sort_and_limit_clamps_limit():
    rows = [PredictionMarket(id=str(i), question="q", volume_usd=float(i)) for i in range(150)]
    assert len(sort_and_limit(rows, limit=999)) == 100
    assert len(sort_and_limit(rows, limit=0)) == 1


def test_sort_and_limit_stable_tie_break_on_id():
    rows = [
        PredictionMarket(id="z", question="q", volume_usd=1.0),
        PredictionMarket(id="a", question="q", volume_usd=1.0),
        PredictionMarket(id="m", question="q", volume_usd=1.0),
    ]
    out = sort_and_limit(rows)
    # All same volume → tie-break on id ascending stays after primary stable sort
    assert [r.id for r in out] == ["a", "m", "z"]


def test_sortable_columns_constant():
    assert set(SORTABLE_COLUMNS) == {"volume_usd", "liquidity_usd", "end_date", "yes_price"}


# ---------- Service (httpx mocked) ----------


class PolymarketServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        polymarket_service._reset_cache()  # noqa: SLF001
        # Default: ensure the gate is off — tests that need it on flip the env var.
        self._patcher = patch.object(
            polymarket_service.runtime_settings,
            "get_bool_setting",
            side_effect=self._gate_lookup,
        )
        self._gate_state = {"POLYMARKET_ENABLED": False}
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()

    def _gate_lookup(self, key: str, default: bool = False) -> bool:
        return bool(self._gate_state.get(key, default))

    def _set_enabled(self, value: bool) -> None:
        self._gate_state["POLYMARKET_ENABLED"] = value

    def _make_recording_client(self, response_data: list[dict[str, Any]] | Exception):
        calls = {"n": 0}

        class _MockClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return None

            async def get(self, url: str, params: dict | None = None):
                calls["n"] += 1
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

    async def test_disabled_by_default_raises_runtime_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await polymarket_service.get_markets()

    async def test_enabled_setting_unblocks_call(self) -> None:
        self._set_enabled(True)
        klass, _ = self._make_recording_client([_market_dict(market_id="x")])
        with patch.object(polymarket_service.httpx, "AsyncClient", klass):
            payload = await polymarket_service.get_markets(limit=10)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["sort_by"], "volume_usd")
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["id"], "x")

    async def test_total_reports_universe_size_not_post_limit(self) -> None:
        """Universe pre-limit count, mirrors screener / coingecko semantics."""
        self._set_enabled(True)
        rows = [_market_dict(market_id=f"m{i}", volume=100.0 * (i + 1)) for i in range(5)]
        klass, _ = self._make_recording_client(rows)
        with patch.object(polymarket_service.httpx, "AsyncClient", klass):
            payload = await polymarket_service.get_markets(limit=2)
        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(payload["total"], 5)

    async def test_caches_within_ttl(self) -> None:
        self._set_enabled(True)
        klass, calls = self._make_recording_client([_market_dict()])
        with patch.object(polymarket_service.httpx, "AsyncClient", klass):
            await polymarket_service.get_markets()
            await polymarket_service.get_markets()
        self.assertEqual(calls["n"], 1)

    async def test_force_refresh_bypasses_cache(self) -> None:
        self._set_enabled(True)
        klass, calls = self._make_recording_client([_market_dict()])
        with patch.object(polymarket_service.httpx, "AsyncClient", klass):
            await polymarket_service.get_markets()
            await polymarket_service.get_markets(force=True)
        self.assertEqual(calls["n"], 2)

    async def test_falls_back_to_cache_on_http_error(self) -> None:
        """First call succeeds; second call's httpx raises → returns prior cache."""
        self._set_enabled(True)
        # Phase 1: prime the cache.
        klass_ok, _ = self._make_recording_client([_market_dict(market_id="cached")])
        with patch.object(polymarket_service.httpx, "AsyncClient", klass_ok):
            first = await polymarket_service.get_markets()

        # Phase 2: upstream fails — should serve cached universe.
        klass_fail, _ = self._make_recording_client(RuntimeError("network down"))
        with patch.object(polymarket_service.httpx, "AsyncClient", klass_fail):
            second = await polymarket_service.get_markets(force=True)

        self.assertEqual(first["rows"][0]["id"], "cached")
        self.assertEqual(second["rows"][0]["id"], "cached")

    async def test_raises_when_no_cache_and_http_fails(self) -> None:
        self._set_enabled(True)
        klass_fail, _ = self._make_recording_client(RuntimeError("network down"))
        with patch.object(polymarket_service.httpx, "AsyncClient", klass_fail):
            with self.assertRaisesRegex(RuntimeError, "Polymarket fetch failed"):
                await polymarket_service.get_markets()


if __name__ == "__main__":
    unittest.main()
