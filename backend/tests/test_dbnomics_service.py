"""DBnomics adapter — pure compute + service caching/error behaviour.

Compute tests build raw dicts by hand. Service tests patch
`dbnomics_service.httpx.AsyncClient` to keep the network off the wire
(mirrors `tests/test_coingecko_service.py`).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.services import dbnomics_service
from core.dbnomics import (
    DBnomicsObservation,
    DBnomicsSeries,
    parse_period_to_date,
    parse_series_doc,
)


# ----- helpers -----


def _doc(
    *,
    provider_code: str = "OECD",
    dataset_code: str = "MEI_FIN",
    series_code: str = "IRSTCB.AUS.M",
    series_name: str | None = "Interest rate, central bank, Australia",
    frequency: str | None = "monthly",
    indexed_at: str | None = "2025-09-01T00:00:00Z",
    period: list[Any] | None = None,
    value: list[Any] | None = None,
) -> dict[str, Any]:
    if period is None:
        period = ["2024-01", "2024-02", "2024-03"]
    if value is None:
        value = [4.35, 4.50, 4.55]
    return {
        "provider_code": provider_code,
        "dataset_code": dataset_code,
        "series_code": series_code,
        "series_name": series_name,
        "@frequency": frequency,
        "indexed_at": indexed_at,
        "period": period,
        "value": value,
    }


class _MockResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


def _make_async_client(
    payload: Any | None = None,
    *,
    status_code: int = 200,
    raises: Exception | None = None,
):
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
            return _MockResponse(payload, status_code=status_code)

    return _Client


def _wrap_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Wrap a series doc in the DBnomics envelope shape."""
    return {"series": {"docs": [doc]}}


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    dbnomics_service._reset_cache()  # noqa: SLF001
    yield
    dbnomics_service._reset_cache()  # noqa: SLF001


# ----- 1-5. parse_period_to_date -----


def test_parse_period_to_date_annual() -> None:
    assert parse_period_to_date("2024") == date(2024, 1, 1)


def test_parse_period_to_date_monthly() -> None:
    assert parse_period_to_date("2024-03") == date(2024, 3, 1)


def test_parse_period_to_date_quarterly_all_four() -> None:
    assert parse_period_to_date("2024-Q1") == date(2024, 1, 1)
    assert parse_period_to_date("2024-Q2") == date(2024, 4, 1)
    assert parse_period_to_date("2024-Q3") == date(2024, 7, 1)
    assert parse_period_to_date("2024-Q4") == date(2024, 10, 1)


def test_parse_period_to_date_daily() -> None:
    assert parse_period_to_date("2024-03-15") == date(2024, 3, 15)


def test_parse_period_to_date_unparseable_returns_none() -> None:
    assert parse_period_to_date("2024W10") is None
    assert parse_period_to_date("abc") is None
    assert parse_period_to_date("") is None


# ----- 6-10. parse_series_doc -----


def test_parse_series_doc_minimal_valid() -> None:
    series = parse_series_doc(_doc())
    assert isinstance(series, DBnomicsSeries)
    assert series.provider_code == "OECD"
    assert series.dataset_code == "MEI_FIN"
    assert series.series_code == "IRSTCB.AUS.M"
    assert series.frequency == "monthly"
    assert len(series.observations) == 3
    assert series.observations[0].period == "2024-01"
    assert series.observations[0].date == date(2024, 1, 1)
    assert series.observations[0].value == 4.35


def test_parse_series_doc_missing_mandatory_returns_none() -> None:
    doc = _doc()
    del doc["period"]
    assert parse_series_doc(doc) is None


def test_parse_series_doc_handles_null_values() -> None:
    series = parse_series_doc(
        _doc(
            period=["2024-01", "2024-02", "2024-03"],
            value=[1.0, None, 3.0],
        )
    )
    assert series is not None
    assert len(series.observations) == 3
    assert series.observations[0].value == 1.0
    assert series.observations[1].value is None
    assert series.observations[2].value == 3.0


def test_parse_series_doc_clamps_mismatched_arrays() -> None:
    series = parse_series_doc(
        _doc(period=["2024", "2025"], value=[1.0])
    )
    assert series is not None
    assert len(series.observations) == 1
    assert series.observations[0].period == "2024"
    assert series.observations[0].value == 1.0


def test_parse_series_doc_sorts_observations_ascending_by_period() -> None:
    series = parse_series_doc(
        _doc(
            period=["2024-03", "2024-01", "2024-02"],
            value=[3.0, 1.0, 2.0],
        )
    )
    assert series is not None
    assert [obs.period for obs in series.observations] == [
        "2024-01",
        "2024-02",
        "2024-03",
    ]
    assert [obs.value for obs in series.observations] == [1.0, 2.0, 3.0]


# ----- 11-16. service caching / errors -----


@pytest.mark.asyncio
async def test_service_caches_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
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
            return _MockResponse(_wrap_doc(_doc()))

    monkeypatch.setattr(dbnomics_service.httpx, "AsyncClient", _CountingClient)

    await dbnomics_service.get_series("OECD", "MEI_FIN", "IRSTCB.AUS.M")
    await dbnomics_service.get_series("OECD", "MEI_FIN", "IRSTCB.AUS.M")

    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_service_force_refresh_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            return _MockResponse(_wrap_doc(_doc()))

    monkeypatch.setattr(dbnomics_service.httpx, "AsyncClient", _CountingClient)

    await dbnomics_service.get_series("OECD", "MEI_FIN", "IRSTCB.AUS.M")
    await dbnomics_service.get_series(
        "OECD", "MEI_FIN", "IRSTCB.AUS.M", force=True
    )

    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_service_falls_back_to_cache_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            return _MockResponse(_wrap_doc(_doc()))

    monkeypatch.setattr(dbnomics_service.httpx, "AsyncClient", _FlakyClient)

    first = await dbnomics_service.get_series("OECD", "MEI_FIN", "IRSTCB.AUS.M")
    assert first["series_code"] == "IRSTCB.AUS.M"

    state["phase"] = "fail"
    second = await dbnomics_service.get_series(
        "OECD", "MEI_FIN", "IRSTCB.AUS.M", force=True
    )
    # Should silently fall back to the prior cached payload.
    assert second["series_code"] == "IRSTCB.AUS.M"
    assert len(second["observations"]) == 3


@pytest.mark.asyncio
async def test_service_raises_lookup_error_on_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_cls = _make_async_client(payload=None, status_code=404)
    monkeypatch.setattr(dbnomics_service.httpx, "AsyncClient", client_cls)

    with pytest.raises(LookupError, match="not found"):
        await dbnomics_service.get_series("XXX", "YYY", "ZZZ")


@pytest.mark.asyncio
async def test_service_raises_lookup_error_on_empty_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_cls = _make_async_client(payload={"series": {"docs": []}})
    monkeypatch.setattr(dbnomics_service.httpx, "AsyncClient", client_cls)

    with pytest.raises(LookupError, match="no series"):
        await dbnomics_service.get_series("OECD", "MEI_FIN", "BOGUS")


@pytest.mark.asyncio
async def test_service_raises_runtime_error_on_5xx_with_no_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_cls = _make_async_client(payload=None, status_code=503)
    monkeypatch.setattr(dbnomics_service.httpx, "AsyncClient", client_cls)

    with pytest.raises(RuntimeError):
        await dbnomics_service.get_series("OECD", "MEI_FIN", "IRSTCB.AUS.M")


# ----- sanity: dataclass shape used internally -----


def test_observation_dataclass_default_value_none() -> None:
    """Defensive: missing keyword args default to None, not raise."""
    obs = DBnomicsObservation(period="2024")
    assert obs.value is None
    assert obs.date is None
