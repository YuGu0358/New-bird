"""CoinGecko adapter — pure compute + service caching/gate behaviour.

Compute tests build raw dicts/rows by hand. Service tests patch
`coingecko_service.httpx.AsyncClient` to keep the network off the wire
(mirrors `tests/test_notifications_channels.py`).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.services import coingecko_service
from core.crypto import (
    CryptoMarketRow,
    parse_markets_payload,
    sort_and_limit,
)


# ----- Fixtures and helpers -----


def _sample_item(
    *,
    coin_id: str = "bitcoin",
    symbol: str = "btc",
    name: str = "Bitcoin",
    rank: int | None = 1,
    price: float | None = 65000.0,
    market_cap: float | None = 1_300_000_000_000.0,
    volume: float | None = 50_000_000_000.0,
    pct_24h: float | None = 2.5,
    image: str | None = "https://example.com/bitcoin.png",
) -> dict[str, Any]:
    return {
        "id": coin_id,
        "symbol": symbol,
        "name": name,
        "market_cap_rank": rank,
        "current_price": price,
        "market_cap": market_cap,
        "total_volume": volume,
        "price_change_percentage_24h": pct_24h,
        "image": image,
    }


def _row(
    *,
    coin_id: str,
    symbol: str | None = None,
    rank: int | None = 1,
    price_usd: float = 100.0,
    market_cap_usd: float | None = 1_000_000.0,
    volume_24h_usd: float | None = 500_000.0,
    change_24h_pct: float | None = 0.01,
) -> CryptoMarketRow:
    return CryptoMarketRow(
        coin_id=coin_id,
        symbol=symbol or coin_id.upper(),
        name=coin_id.capitalize(),
        rank=rank,
        price_usd=price_usd,
        market_cap_usd=market_cap_usd,
        volume_24h_usd=volume_24h_usd,
        change_24h_pct=change_24h_pct,
        image_url=None,
    )


class _MockResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> Any:
        return self._payload


def _make_async_client(payload: Any | None = None, *, raises: Exception | None = None):
    """Build a mock `httpx.AsyncClient` that returns `payload` on GET."""

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, **kwargs: Any):
            if raises is not None:
                raise raises
            return _MockResponse(payload)

    return _Client


def _reset_cache() -> None:
    coingecko_service._cache = None  # noqa: SLF001


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Point the settings DB at a per-test sqlite so stored values don't bleed."""
    monkeypatch.setattr(
        coingecko_service.runtime_settings,
        "DATABASE_FILE",
        tmp_path / "settings.db",
    )
    # Make sure the env starts clean — individual tests opt-in via setenv.
    monkeypatch.delenv("CRYPTO_COINGECKO_ENABLED", raising=False)
    _reset_cache()
    yield
    _reset_cache()


# ----- 1. Disabled by default -----


@pytest.mark.asyncio
async def test_disabled_by_default_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError, match="disabled"):
        await coingecko_service.get_markets()


# ----- 2. Enabling unblocks the call -----


@pytest.mark.asyncio
async def test_enabled_setting_unblocks_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYPTO_COINGECKO_ENABLED", "true")
    client_cls = _make_async_client(payload=[_sample_item()])
    monkeypatch.setattr(coingecko_service.httpx, "AsyncClient", client_cls)

    payload = await coingecko_service.get_markets(limit=10)

    assert payload["total"] == 1
    assert payload["rows"][0]["coin_id"] == "bitcoin"
    assert payload["rows"][0]["symbol"] == "BTC"


# ----- 3-5. parse_markets_payload -----


def test_parse_markets_payload_drops_malformed_rows() -> None:
    items = [
        _sample_item(coin_id="bitcoin"),
        _sample_item(coin_id=None),  # malformed: id missing
        _sample_item(coin_id="ethereum", symbol="eth", name="Ethereum"),
    ]
    rows = parse_markets_payload(items)
    assert len(rows) == 2
    assert {r.coin_id for r in rows} == {"bitcoin", "ethereum"}


def test_parse_markets_payload_handles_missing_optional_keys() -> None:
    minimal = {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "current_price": 65000.0,
    }
    rows = parse_markets_payload([minimal])
    assert len(rows) == 1
    row = rows[0]
    assert row.coin_id == "bitcoin"
    assert row.symbol == "BTC"
    assert row.name == "Bitcoin"
    assert row.price_usd == 65000.0
    assert row.rank is None
    assert row.market_cap_usd is None
    assert row.volume_24h_usd is None
    assert row.change_24h_pct is None
    assert row.image_url is None


def test_parse_markets_payload_converts_pct_to_fraction() -> None:
    rows = parse_markets_payload([_sample_item(pct_24h=5.5)])
    assert len(rows) == 1
    # 5.5% → 0.055 fraction.
    assert rows[0].change_24h_pct == pytest.approx(0.055)


# ----- 6-9. sort_and_limit -----


def test_sort_and_limit_volume_desc_default() -> None:
    rows = [
        _row(coin_id="aaa", volume_24h_usd=1.0),
        _row(coin_id="bbb", volume_24h_usd=None),
        _row(coin_id="ccc", volume_24h_usd=10.0),
        _row(coin_id="ddd", volume_24h_usd=5.0),
    ]
    out = sort_and_limit(rows, limit=10)
    coin_ids = [r.coin_id for r in out]
    # 10 > 5 > 1, then None last.
    assert coin_ids == ["ccc", "ddd", "aaa", "bbb"]


def test_sort_and_limit_unknown_sort_by_raises_value_error() -> None:
    rows = [_row(coin_id="aaa")]
    with pytest.raises(ValueError):
        sort_and_limit(rows, sort_by="not_a_column")


def test_sort_and_limit_clamps_limit_to_range() -> None:
    rows = [_row(coin_id=f"c{i:03d}", volume_24h_usd=float(i)) for i in range(300)]

    out_low = sort_and_limit(rows, limit=0)
    assert len(out_low) == 1

    out_high = sort_and_limit(rows, limit=999)
    assert len(out_high) == 250


def test_sort_and_limit_stable_tie_break_on_symbol() -> None:
    """Identical primary key → tie-break by rank asc, then symbol asc.
    With identical ranks, this means symbol asc is the deciding key."""
    rows = [
        _row(coin_id="m", symbol="MSFT", rank=5, volume_24h_usd=42.0),
        _row(coin_id="a", symbol="AAPL", rank=5, volume_24h_usd=42.0),
        _row(coin_id="n", symbol="NVDA", rank=5, volume_24h_usd=42.0),
    ]
    out = sort_and_limit(rows, limit=10)
    assert [r.symbol for r in out] == ["AAPL", "MSFT", "NVDA"]


# ----- 10-13. service caching and fallbacks -----


@pytest.mark.asyncio
async def test_service_caches_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYPTO_COINGECKO_ENABLED", "true")
    call_count = {"n": 0}

    class _CountingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, **kwargs: Any):
            call_count["n"] += 1
            return _MockResponse([_sample_item()])

    monkeypatch.setattr(coingecko_service.httpx, "AsyncClient", _CountingClient)

    await coingecko_service.get_markets(limit=10)
    await coingecko_service.get_markets(limit=10)

    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_service_force_refresh_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRYPTO_COINGECKO_ENABLED", "true")
    call_count = {"n": 0}

    class _CountingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, **kwargs: Any):
            call_count["n"] += 1
            return _MockResponse([_sample_item()])

    monkeypatch.setattr(coingecko_service.httpx, "AsyncClient", _CountingClient)

    await coingecko_service.get_markets(limit=10)
    await coingecko_service.get_markets(limit=10, force=True)

    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_service_falls_back_to_cache_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRYPTO_COINGECKO_ENABLED", "true")

    state = {"phase": "ok"}

    class _FlakyClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, **kwargs: Any):
            if state["phase"] == "fail":
                raise RuntimeError("upstream blew up")
            return _MockResponse([_sample_item(coin_id="bitcoin")])

    monkeypatch.setattr(coingecko_service.httpx, "AsyncClient", _FlakyClient)

    first = await coingecko_service.get_markets(limit=10)
    assert first["rows"][0]["coin_id"] == "bitcoin"

    # Force a refresh on the next call AND make the upstream raise.
    state["phase"] = "fail"
    second = await coingecko_service.get_markets(limit=10, force=True)
    # Should silently fall back to the prior cached payload.
    assert second["rows"][0]["coin_id"] == "bitcoin"


@pytest.mark.asyncio
async def test_service_raises_when_no_cache_and_http_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRYPTO_COINGECKO_ENABLED", "true")
    client_cls = _make_async_client(raises=RuntimeError("no network"))
    monkeypatch.setattr(coingecko_service.httpx, "AsyncClient", client_cls)

    with pytest.raises(RuntimeError):
        await coingecko_service.get_markets(limit=10)
