"""Tests for heatmap_service: pure-compute, cache, and router shape.

Mirrors `test_sector_rotation.py` — patches the blocking yfinance fetcher
at the service-module boundary so we never hit the network.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.services import heatmap_service
from core.screener import SCREENER_UNIVERSE


def test_flat_universe_length_matches_screener():
    """_flat_universe must enumerate every entry in SCREENER_UNIVERSE."""
    flat = heatmap_service._flat_universe()  # noqa: SLF001
    assert len(flat) == len(SCREENER_UNIVERSE)
    # Each pair is (symbol, sector) and matches the source.
    expected = [(e.symbol, e.sector) for e in SCREENER_UNIVERSE]
    assert flat == expected


def test_compute_change_pct_handles_short_input():
    assert heatmap_service._compute_change_pct([]) is None
    assert heatmap_service._compute_change_pct([100.0]) is None
    assert heatmap_service._compute_change_pct([0.0, 100.0]) is None
    assert heatmap_service._compute_change_pct([100.0, 110.0]) == pytest.approx(0.10)


def test_build_payload_pure_happy_path():
    """Pinned math: 2 symbols, caps 100 / 200, changes 1% / 2%.

    Weighted sector change = (100*0.01 + 200*0.02) / 300 = 0.0166666...
    """
    universe = [("AAA", "Tech"), ("BBB", "Tech")]
    raw = {
        "closes_by_symbol": {
            "AAA": [100.0, 101.0],  # +1.0%
            "BBB": [50.0, 51.0],    # +2.0%
        },
        "market_cap_by_symbol": {"AAA": 100.0, "BBB": 200.0},
    }
    tiles, sectors = heatmap_service._build_payload(raw, universe)  # noqa: SLF001

    assert len(tiles) == 2
    by_symbol = {t["symbol"]: t for t in tiles}
    assert by_symbol["AAA"]["change_1d_pct"] == pytest.approx(0.01)
    assert by_symbol["BBB"]["change_1d_pct"] == pytest.approx(0.02)
    assert by_symbol["AAA"]["latest_close"] == pytest.approx(101.0)
    assert by_symbol["AAA"]["sector"] == "Tech"
    assert by_symbol["AAA"]["market_cap"] == 100.0

    assert len(sectors) == 1
    row = sectors[0]
    assert row["sector"] == "Tech"
    assert row["constituent_count"] == 2
    assert row["total_market_cap"] == pytest.approx(300.0)
    expected_weighted = (100.0 * 0.01 + 200.0 * 0.02) / 300.0
    assert row["change_1d_pct"] == pytest.approx(expected_weighted)
    # Sanity: weighted is NOT a simple average ((0.01+0.02)/2 = 0.015).
    assert row["change_1d_pct"] != pytest.approx(0.015)


def test_build_payload_empty_fetch_yields_none_aggregate():
    """No closes + no caps → tiles all-None, sector aggregate None."""
    universe = [("AAA", "Tech"), ("BBB", "Tech")]
    raw = {"closes_by_symbol": {}, "market_cap_by_symbol": {}}
    tiles, sectors = heatmap_service._build_payload(raw, universe)  # noqa: SLF001

    for t in tiles:
        assert t["change_1d_pct"] is None
        assert t["market_cap"] is None
        assert t["latest_close"] is None

    assert len(sectors) == 1
    row = sectors[0]
    assert row["constituent_count"] == 2
    assert row["total_market_cap"] is None
    assert row["change_1d_pct"] is None


def test_build_payload_skips_symbols_missing_cap_or_change():
    """Symbol with only one close → change=None and excluded from weight numerator.

    Symbol with cap=None → also excluded. Both still counted in
    `constituent_count`.
    """
    universe = [
        ("AAA", "Tech"),
        ("BBB", "Tech"),  # only one close → change=None → excluded
        ("CCC", "Tech"),  # no cap → excluded
    ]
    raw = {
        "closes_by_symbol": {
            "AAA": [100.0, 102.0],   # +2%
            "BBB": [50.0],           # only one bar
            "CCC": [10.0, 11.0],     # +10% but no cap
        },
        "market_cap_by_symbol": {
            "AAA": 500.0,
            "BBB": 300.0,
            # CCC missing
        },
    }
    tiles, sectors = heatmap_service._build_payload(raw, universe)  # noqa: SLF001

    by_symbol = {t["symbol"]: t for t in tiles}
    assert by_symbol["BBB"]["change_1d_pct"] is None
    assert by_symbol["CCC"]["market_cap"] is None
    assert by_symbol["CCC"]["change_1d_pct"] == pytest.approx(0.10)

    assert len(sectors) == 1
    row = sectors[0]
    assert row["constituent_count"] == 3
    # Total cap counts AAA + BBB (CCC missing) = 800.
    assert row["total_market_cap"] == pytest.approx(800.0)
    # Weighted change uses ONLY rows with both cap+change. Only AAA qualifies.
    # numerator = 500 * 0.02 = 10 ; denominator = 500 ; weighted = 0.02
    assert row["change_1d_pct"] == pytest.approx(0.02)


def test_build_payload_one_close_yields_none_change():
    """Single close means we can't compute a 1d change."""
    universe = [("AAA", "Tech")]
    raw = {
        "closes_by_symbol": {"AAA": [100.0]},
        "market_cap_by_symbol": {"AAA": 100.0},
    }
    tiles, _ = heatmap_service._build_payload(raw, universe)  # noqa: SLF001
    assert tiles[0]["change_1d_pct"] is None
    # latest_close still surfaces even with one bar.
    assert tiles[0]["latest_close"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_service_uses_cache():
    """Two calls within the TTL hit yfinance only once."""
    heatmap_service._reset_cache()  # noqa: SLF001
    call_count = {"n": 0}

    def fake_download(symbols: list[str]):
        call_count["n"] += 1
        return {
            "closes_by_symbol": {sym: [100.0, 101.0] for sym in symbols},
            "market_cap_by_symbol": {sym: 1_000_000.0 for sym in symbols},
        }

    with patch.object(
        heatmap_service,
        "_download_blocking",
        side_effect=fake_download,
    ):
        first = await heatmap_service.get_symbol_heatmap()
        second = await heatmap_service.get_sector_heatmap()

    assert call_count["n"] == 1
    assert len(first["items"]) == len(SCREENER_UNIVERSE)
    # 11 sectors in the curated universe.
    assert len(second["items"]) == 11
    # Both views built off the same cache slot → same generated_at.
    assert first["generated_at"] == second["generated_at"]


@pytest.mark.asyncio
async def test_service_force_refresh_bypasses_cache():
    heatmap_service._reset_cache()  # noqa: SLF001
    call_count = {"n": 0}

    def fake_download(symbols: list[str]):
        call_count["n"] += 1
        return {
            "closes_by_symbol": {sym: [100.0, 101.0] for sym in symbols},
            "market_cap_by_symbol": {sym: 1_000_000.0 for sym in symbols},
        }

    with patch.object(
        heatmap_service,
        "_download_blocking",
        side_effect=fake_download,
    ):
        await heatmap_service.get_symbol_heatmap()
        await heatmap_service.get_symbol_heatmap(force=True)

    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_service_handles_empty_yfinance_response():
    """Empty download → tiles all-None, sectors zero/None aggregates."""
    heatmap_service._reset_cache()  # noqa: SLF001
    with patch.object(
        heatmap_service,
        "_download_blocking",
        return_value={"closes_by_symbol": {}, "market_cap_by_symbol": {}},
    ):
        sym_payload = await heatmap_service.get_symbol_heatmap()
        sec_payload = await heatmap_service.get_sector_heatmap()

    assert len(sym_payload["items"]) == len(SCREENER_UNIVERSE)
    for tile in sym_payload["items"]:
        assert tile["change_1d_pct"] is None
        assert tile["market_cap"] is None
        assert tile["latest_close"] is None

    assert len(sec_payload["items"]) == 11
    for row in sec_payload["items"]:
        assert row["total_market_cap"] is None
        assert row["change_1d_pct"] is None
        assert row["constituent_count"] == 5  # 5 names per sector


def test_router_endpoints_return_200():
    """Smoke the FastAPI router shape end-to-end with a stubbed fetcher."""
    heatmap_service._reset_cache()  # noqa: SLF001
    from app.main import app

    def fake_download(symbols: list[str]):
        return {
            "closes_by_symbol": {sym: [100.0, 101.0] for sym in symbols},
            "market_cap_by_symbol": {sym: 1_000_000.0 for sym in symbols},
        }

    with patch.object(
        heatmap_service,
        "_download_blocking",
        side_effect=fake_download,
    ):
        client = TestClient(app)
        sym_resp = client.get("/api/heatmap/symbols")
        sec_resp = client.get("/api/heatmap/sectors")

    assert sym_resp.status_code == 200
    sym_body = sym_resp.json()
    assert "items" in sym_body
    assert "generated_at" in sym_body
    assert len(sym_body["items"]) == len(SCREENER_UNIVERSE)
    first_tile = sym_body["items"][0]
    for key in ("symbol", "sector", "market_cap", "change_1d_pct", "latest_close"):
        assert key in first_tile

    assert sec_resp.status_code == 200
    sec_body = sec_resp.json()
    assert "items" in sec_body
    assert len(sec_body["items"]) == 11
    first_row = sec_body["items"][0]
    for key in ("sector", "total_market_cap", "change_1d_pct", "constituent_count"):
        assert key in first_row
