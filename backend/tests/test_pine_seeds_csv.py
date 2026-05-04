"""Unit tests for pine-seeds CSV row builders and symbol_info helper."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from core.pine_seeds import (
    append_csv_row,
    build_levels_row,
    build_macro_row,
    build_val_row,
    symbol_info_for,
)


SNAPSHOT = date(2026, 4, 27)


def _expected_unix(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


class TestBuildLevelsRow:
    def test_full_summary_maps_to_ohlcv(self) -> None:
        gex_summary = {
            "call_wall": 580.0,
            "put_wall": 540.0,
            "max_pain": 555.0,
            "zero_gamma": 565.5,
            "total_chain_oi": 12345,
        }
        row = build_levels_row(snapshot_date=SNAPSHOT, gex_summary=gex_summary)
        assert set(row.keys()) == {"time", "open", "high", "low", "close", "volume"}
        ts = int(row["time"])
        assert ts == _expected_unix(SNAPSHOT)
        assert datetime.fromtimestamp(ts, tz=timezone.utc).date() == SNAPSHOT
        assert row["open"] == "580.0"
        assert row["high"] == "540.0"
        assert row["low"] == "555.0"
        assert row["close"] == "565.5"
        assert row["volume"] == "12345"

    def test_call_wall_none_renders_empty(self) -> None:
        gex_summary = {
            "call_wall": None,
            "put_wall": 540.0,
            "max_pain": 555.0,
            "zero_gamma": 565.5,
            "total_chain_oi": 12345,
        }
        row = build_levels_row(snapshot_date=SNAPSHOT, gex_summary=gex_summary)
        assert row["open"] == ""
        # Other fields still populated
        assert row["high"] == "540.0"
        assert row["volume"] == "12345"

    def test_missing_total_chain_oi_falls_back_to_by_strike_sum_or_empty(self) -> None:
        # Missing entirely → empty string
        gex_summary = {
            "call_wall": 580.0,
            "put_wall": 540.0,
            "max_pain": 555.0,
            "zero_gamma": 565.5,
        }
        row = build_levels_row(snapshot_date=SNAPSHOT, gex_summary=gex_summary)
        assert row["volume"] == ""

        # by_strike sum fallback
        gex_summary_with_strikes = {
            "call_wall": 580.0,
            "put_wall": 540.0,
            "max_pain": 555.0,
            "zero_gamma": 565.5,
            "by_strike": [
                {"strike": 540.0, "oi": 100},
                {"strike": 555.0, "oi": 200},
                {"strike": 580.0, "oi": 300},
            ],
        }
        row2 = build_levels_row(snapshot_date=SNAPSHOT, gex_summary=gex_summary_with_strikes)
        assert row2["volume"] == "600"


class TestBuildValRow:
    def test_all_bands_none_produces_empty_cells(self) -> None:
        pe_channel = {
            "fair_p25": None,
            "fair_p95": None,
            "fair_p5": None,
            "fair_p50": None,
            "sample_size": None,
        }
        row = build_val_row(snapshot_date=SNAPSHOT, pe_channel=pe_channel)
        assert int(row["time"]) == _expected_unix(SNAPSHOT)
        assert row["open"] == ""
        assert row["high"] == ""
        assert row["low"] == ""
        assert row["close"] == ""
        assert row["volume"] == ""

    def test_full_bands_map_correctly(self) -> None:
        pe_channel = {
            "fair_p25": 110.5,
            "fair_p95": 165.0,
            "fair_p5": 92.25,
            "fair_p50": 130.0,
            "sample_size": 5040,
        }
        row = build_val_row(snapshot_date=SNAPSHOT, pe_channel=pe_channel)
        assert int(row["time"]) == _expected_unix(SNAPSHOT)
        assert row["open"] == "110.5"
        assert row["high"] == "165.0"
        assert row["low"] == "92.25"
        assert row["close"] == "130.0"
        assert row["volume"] == "5040"


class TestBuildMacroRow:
    def test_signal_counts_map_to_ohlcv(self) -> None:
        ensemble = {
            "total_core": 4,
            "signals": {"ok": 2, "warn": 1, "danger": 1, "neutral": 0},
        }
        row = build_macro_row(snapshot_date=SNAPSHOT, ensemble=ensemble)
        assert int(row["time"]) == _expected_unix(SNAPSHOT)
        assert row["open"] == "2"
        assert row["high"] == "1"
        assert row["low"] == "1"
        assert row["close"] == "0"
        assert row["volume"] == "4"


class TestAppendCsvRow:
    def test_creates_file_with_header_on_first_call(self, tmp_path: Path) -> None:
        path = tmp_path / "newbird_spy_levels.csv"
        row = build_levels_row(
            snapshot_date=SNAPSHOT,
            gex_summary={
                "call_wall": 580.0,
                "put_wall": 540.0,
                "max_pain": 555.0,
                "zero_gamma": 565.5,
                "total_chain_oi": 12345,
            },
        )
        result = append_csv_row(path, row)
        assert result is True
        assert path.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "time,open,high,low,close,volume"
        assert len(lines) == 2

    def test_idempotent_same_time_returns_false_no_change(self, tmp_path: Path) -> None:
        path = tmp_path / "newbird_spy_levels.csv"
        row = build_levels_row(
            snapshot_date=SNAPSHOT,
            gex_summary={
                "call_wall": 580.0,
                "put_wall": 540.0,
                "max_pain": 555.0,
                "zero_gamma": 565.5,
                "total_chain_oi": 12345,
            },
        )
        first = append_csv_row(path, row)
        assert first is True
        before = path.read_text(encoding="utf-8")
        before_lines = before.splitlines()

        second = append_csv_row(path, row)
        assert second is False
        after = path.read_text(encoding="utf-8")
        after_lines = after.splitlines()
        assert before == after
        assert len(before_lines) == len(after_lines) == 2

    def test_new_time_appends_growing_file_by_one(self, tmp_path: Path) -> None:
        path = tmp_path / "newbird_spy_levels.csv"
        row1 = build_levels_row(
            snapshot_date=SNAPSHOT,
            gex_summary={
                "call_wall": 580.0,
                "put_wall": 540.0,
                "max_pain": 555.0,
                "zero_gamma": 565.5,
                "total_chain_oi": 12345,
            },
        )
        row2 = build_levels_row(
            snapshot_date=date(2026, 4, 28),
            gex_summary={
                "call_wall": 582.0,
                "put_wall": 538.0,
                "max_pain": 556.0,
                "zero_gamma": 566.0,
                "total_chain_oi": 13000,
            },
        )
        assert append_csv_row(path, row1) is True
        assert append_csv_row(path, row2) is True
        lines = path.read_text(encoding="utf-8").splitlines()
        # Header + two data rows
        assert len(lines) == 3
        assert lines[0] == "time,open,high,low,close,volume"


class TestSymbolInfoFor:
    def test_levels_returns_expected_dict(self) -> None:
        info = symbol_info_for("SPY", "LEVELS")
        assert info["symbol"] == ["NEWBIRD_SPY_LEVELS"]
        assert info["description"] == [
            "Newbird options walls (call wall, put wall, max pain)"
        ]
        assert info["currency"] == "USD"
        assert info["session-regular"] == "0930-1600"
        assert info["timezone"] == "America/New_York"
        assert info["type"] == "indicator"

    def test_unknown_kind_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            symbol_info_for("SPY", "TRENDS")  # type: ignore[arg-type]
