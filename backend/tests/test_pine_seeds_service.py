"""Tests for the pine-seeds orchestration service."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import macro_service, options_chain_service, valuation_service
from app.services import pine_seeds_service


def _gex_summary(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "spot": 555.0,
        "call_wall": 580.0,
        "put_wall": 540.0,
        "max_pain": 555.0,
        "zero_gamma": 565.5,
        "total_chain_oi": 12345,
        "by_strike": [],
    }


def _pe_channel(ticker: str, *, all_none: bool = False) -> dict:
    if all_none:
        return {
            "ticker": ticker,
            "fair_p25": None,
            "fair_p95": None,
            "fair_p5": None,
            "fair_p50": None,
            "sample_size": None,
        }
    return {
        "ticker": ticker,
        "fair_p25": 110.5,
        "fair_p95": 165.0,
        "fair_p5": 92.25,
        "fair_p50": 130.0,
        "sample_size": 5040,
    }


def _macro_dashboard() -> dict:
    return {
        "indicators": [],
        "ensemble": {
            "total_core": 4,
            "signals": {"ok": 2, "warn": 1, "danger": 1, "neutral": 0},
        },
    }


@pytest.fixture
def mock_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default mocks: every ticker gets a valid GEX/PE; macro returns full ensemble."""

    async def fake_gex(ticker: str, **_kwargs):
        return _gex_summary(ticker)

    async def fake_pe(ticker: str, **_kwargs):
        return _pe_channel(ticker)

    async def fake_dashboard(**_kwargs):
        return _macro_dashboard()

    monkeypatch.setattr(options_chain_service, "get_gex_summary", fake_gex)
    monkeypatch.setattr(valuation_service, "fetch_pe_channel", fake_pe)
    monkeypatch.setattr(macro_service, "get_dashboard", fake_dashboard)


def test_happy_path_two_symbols_plus_macro(
    tmp_path: Path,
    mock_services: None,
) -> None:
    """5 CSVs + 5 JSONs + seeds_categories.json with all entries."""
    import asyncio

    summary = asyncio.run(
        pine_seeds_service.export_snapshot(tmp_path, symbols=["SPY", "NVDA"])
    )

    data_dir = tmp_path / "data"
    info_dir = tmp_path / "symbol_info"

    csv_files = sorted(p.name for p in data_dir.iterdir() if p.is_file())
    json_files = sorted(p.name for p in info_dir.iterdir() if p.is_file())

    assert csv_files == sorted([
        "NEWBIRD_SPY_LEVELS, 1D.csv",
        "NEWBIRD_NVDA_LEVELS, 1D.csv",
        "NEWBIRD_SPY_VAL, 1D.csv",
        "NEWBIRD_NVDA_VAL, 1D.csv",
        "NEWBIRD_MACRO_ENSEMBLE, 1D.csv",
    ])
    assert json_files == sorted([
        "NEWBIRD_SPY_LEVELS.json",
        "NEWBIRD_NVDA_LEVELS.json",
        "NEWBIRD_SPY_VAL.json",
        "NEWBIRD_NVDA_VAL.json",
        "NEWBIRD_MACRO_ENSEMBLE.json",
    ])

    cats_path = tmp_path / "seeds_categories.json"
    assert cats_path.exists()
    cats = json.loads(cats_path.read_text(encoding="utf-8"))
    assert "Newbird Signals" in cats
    expected_tickers = {
        "NEWBIRD_SPY_LEVELS",
        "NEWBIRD_SPY_VAL",
        "NEWBIRD_NVDA_LEVELS",
        "NEWBIRD_NVDA_VAL",
        "NEWBIRD_MACRO_ENSEMBLE",
    }
    assert set(cats["Newbird Signals"]) == expected_tickers

    assert summary["workspace"] == str(tmp_path)
    assert set(summary["tickers_emitted"]) == expected_tickers
    assert summary["rows_written"] == 5
    assert summary["rows_skipped"] == 0
    assert summary["errors"] == []


def test_idempotent_rerun(
    tmp_path: Path,
    mock_services: None,
) -> None:
    """Second call: 0 written, 5 skipped, no errors, no extra files."""
    import asyncio

    asyncio.run(pine_seeds_service.export_snapshot(tmp_path, symbols=["SPY", "NVDA"]))

    csv_count_first = len(list((tmp_path / "data").iterdir()))

    summary2 = asyncio.run(
        pine_seeds_service.export_snapshot(tmp_path, symbols=["SPY", "NVDA"])
    )

    csv_count_second = len(list((tmp_path / "data").iterdir()))
    assert csv_count_first == csv_count_second
    assert summary2["rows_written"] == 0
    assert summary2["rows_skipped"] == 5
    assert summary2["errors"] == []


def test_pe_channel_unavailable_for_one_symbol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NVDA PE all-None → no val CSV; SPY still gets val + levels."""
    import asyncio

    async def fake_gex(ticker: str, **_kwargs):
        return _gex_summary(ticker)

    async def fake_pe(ticker: str, **_kwargs):
        if ticker.upper() == "NVDA":
            return _pe_channel(ticker, all_none=True)
        return _pe_channel(ticker)

    async def fake_dashboard(**_kwargs):
        return _macro_dashboard()

    monkeypatch.setattr(options_chain_service, "get_gex_summary", fake_gex)
    monkeypatch.setattr(valuation_service, "fetch_pe_channel", fake_pe)
    monkeypatch.setattr(macro_service, "get_dashboard", fake_dashboard)

    summary = asyncio.run(
        pine_seeds_service.export_snapshot(
            tmp_path, symbols=["SPY", "NVDA"], include_macro=False
        )
    )

    data_dir = tmp_path / "data"
    assert (data_dir / "NEWBIRD_SPY_LEVELS, 1D.csv").exists()
    assert (data_dir / "NEWBIRD_NVDA_LEVELS, 1D.csv").exists()
    assert (data_dir / "NEWBIRD_SPY_VAL, 1D.csv").exists()
    assert not (data_dir / "NEWBIRD_NVDA_VAL, 1D.csv").exists()

    assert "NEWBIRD_NVDA_VAL" not in summary["tickers_emitted"]
    assert "NEWBIRD_SPY_VAL" in summary["tickers_emitted"]


def test_options_chain_raises_for_one_symbol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QQQ raises → errors entry, SPY processes fine."""
    import asyncio

    async def fake_gex(ticker: str, **_kwargs):
        if ticker.upper() == "QQQ":
            raise RuntimeError("upstream unavailable")
        return _gex_summary(ticker)

    async def fake_pe(ticker: str, **_kwargs):
        return _pe_channel(ticker)

    async def fake_dashboard(**_kwargs):
        return _macro_dashboard()

    monkeypatch.setattr(options_chain_service, "get_gex_summary", fake_gex)
    monkeypatch.setattr(valuation_service, "fetch_pe_channel", fake_pe)
    monkeypatch.setattr(macro_service, "get_dashboard", fake_dashboard)

    summary = asyncio.run(
        pine_seeds_service.export_snapshot(
            tmp_path, symbols=["SPY", "QQQ"], include_macro=False
        )
    )

    qqq_errors = [e for e in summary["errors"] if e["ticker"] == "QQQ"]
    assert len(qqq_errors) == 1
    assert qqq_errors[0]["kind"] == "LEVELS"
    assert qqq_errors[0]["error"] == "upstream unavailable"

    data_dir = tmp_path / "data"
    assert (data_dir / "NEWBIRD_SPY_LEVELS, 1D.csv").exists()
    assert not (data_dir / "NEWBIRD_QQQ_LEVELS, 1D.csv").exists()
    # SPY VAL still emitted; QQQ VAL still emitted (PE doesn't depend on chain)
    assert (data_dir / "NEWBIRD_SPY_VAL, 1D.csv").exists()


def test_symbols_none_reads_pine_seeds_watchlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """symbols=None + PINE_SEEDS_WATCHLIST set → use watchlist."""
    import asyncio

    from app import runtime_settings

    seen: list[str] = []

    async def fake_gex(ticker: str, **_kwargs):
        seen.append(ticker.upper())
        return _gex_summary(ticker)

    async def fake_pe(ticker: str, **_kwargs):
        return _pe_channel(ticker)

    async def fake_dashboard(**_kwargs):
        return _macro_dashboard()

    def fake_get_setting(key: str, default: str | None = None) -> str | None:
        if key == "PINE_SEEDS_WATCHLIST":
            return "AAPL,TSLA"
        return default

    monkeypatch.setattr(options_chain_service, "get_gex_summary", fake_gex)
    monkeypatch.setattr(valuation_service, "fetch_pe_channel", fake_pe)
    monkeypatch.setattr(macro_service, "get_dashboard", fake_dashboard)
    monkeypatch.setattr(runtime_settings, "get_setting", fake_get_setting)

    asyncio.run(pine_seeds_service.export_snapshot(tmp_path, include_macro=False))

    assert sorted(seen) == ["AAPL", "TSLA"]


def test_symbols_none_and_watchlist_unset_uses_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """symbols=None + watchlist empty → defaults SPY/QQQ/NVDA/AAPL."""
    import asyncio

    from app import runtime_settings

    seen: list[str] = []

    async def fake_gex(ticker: str, **_kwargs):
        seen.append(ticker.upper())
        return _gex_summary(ticker)

    async def fake_pe(ticker: str, **_kwargs):
        return _pe_channel(ticker)

    async def fake_dashboard(**_kwargs):
        return _macro_dashboard()

    def fake_get_setting(key: str, default: str | None = None) -> str | None:
        if key == "PINE_SEEDS_WATCHLIST":
            return ""
        return default

    monkeypatch.setattr(options_chain_service, "get_gex_summary", fake_gex)
    monkeypatch.setattr(valuation_service, "fetch_pe_channel", fake_pe)
    monkeypatch.setattr(macro_service, "get_dashboard", fake_dashboard)
    monkeypatch.setattr(runtime_settings, "get_setting", fake_get_setting)

    asyncio.run(pine_seeds_service.export_snapshot(tmp_path, include_macro=False))

    assert sorted(seen) == ["AAPL", "NVDA", "QQQ", "SPY"]
