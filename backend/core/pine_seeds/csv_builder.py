"""CSV row builders for TradingView pine-seeds feeds.

Each Newbird ticker (LEVELS / VAL / MACRO) is published as a daily CSV in the
pine-seeds repo with the standard OHLCV header. The pine-seeds reader expects
``time`` as integer unix seconds at UTC midnight; OHLCV columns hold whatever
scalar makes sense for the underlying signal. We re-purpose the columns:

* LEVELS  → call_wall / put_wall / max_pain / zero_gamma / total_chain_oi
* VAL     → fair_p25  / fair_p95 / fair_p5   / fair_p50    / sample_size
* MACRO   → signals.ok / warn / danger / neutral / total_core

This module is pure stdlib — no pandas, no I/O beyond the one CSV file the
caller hands us. ``append_csv_row`` is idempotent on ``time`` so re-running a
daily snapshot is safe.
"""
from __future__ import annotations

import csv
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

CSV_HEADER: tuple[str, ...] = ("time", "open", "high", "low", "close", "volume")


def _to_unix_seconds(d: date) -> int:
    """Convert a date to unix-seconds at 00:00:00 UTC."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _format_value(v: Any) -> str:
    """Format an OHLCV cell.

    None / NaN  → empty string
    bool        → "1" / "0" (so signal counts render cleanly)
    int/float   → str(v) (no leading zeros, no scientific notation tricks)
    other       → str(v)
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        return str(v)
    if isinstance(v, int):
        return str(v)
    return str(v)


def _levels_volume(gex_summary: dict) -> Any:
    """Pick total_chain_oi if present, else sum by_strike OI, else None."""
    total = gex_summary.get("total_chain_oi")
    if total is not None:
        return total
    by_strike = gex_summary.get("by_strike")
    if isinstance(by_strike, list) and by_strike:
        s = 0
        any_oi = False
        for row in by_strike:
            oi = row.get("oi") if isinstance(row, dict) else None
            if oi is None:
                continue
            any_oi = True
            try:
                s += int(oi)
            except (TypeError, ValueError):
                continue
        if any_oi:
            return s
    return None


def build_levels_row(*, snapshot_date: date, gex_summary: dict) -> dict[str, str]:
    """One row for ``NEWBIRD_<SYM>_LEVELS``.

    Maps gex_summary fields to OHLCV:
        time   = unix seconds at UTC midnight
        open   = call_wall
        high   = put_wall
        low    = max_pain
        close  = zero_gamma
        volume = total_chain_oi (or sum of by_strike OI as a fallback)
    Missing fields render as empty string.
    """
    return {
        "time": _format_value(_to_unix_seconds(snapshot_date)),
        "open": _format_value(gex_summary.get("call_wall")),
        "high": _format_value(gex_summary.get("put_wall")),
        "low": _format_value(gex_summary.get("max_pain")),
        "close": _format_value(gex_summary.get("zero_gamma")),
        "volume": _format_value(_levels_volume(gex_summary)),
    }


def build_val_row(*, snapshot_date: date, pe_channel: dict) -> dict[str, str]:
    """One row for ``NEWBIRD_<SYM>_VAL``.

    Maps PE-channel:
        time   = unix seconds at UTC midnight
        open   = fair_p25
        high   = fair_p95
        low    = fair_p5
        close  = fair_p50
        volume = sample_size
    Missing fields render as empty string.
    """
    return {
        "time": _format_value(_to_unix_seconds(snapshot_date)),
        "open": _format_value(pe_channel.get("fair_p25")),
        "high": _format_value(pe_channel.get("fair_p95")),
        "low": _format_value(pe_channel.get("fair_p5")),
        "close": _format_value(pe_channel.get("fair_p50")),
        "volume": _format_value(pe_channel.get("sample_size")),
    }


def build_macro_row(*, snapshot_date: date, ensemble: dict) -> dict[str, str]:
    """One row for ``NEWBIRD_MACRO_ENSEMBLE``.

    Maps ensemble signal counts:
        time   = unix seconds at UTC midnight
        open   = signals.ok
        high   = signals.warn
        low    = signals.danger
        close  = signals.neutral
        volume = total_core
    The ensemble dict has shape
    ``{"total_core": int, "signals": {ok, warn, danger, neutral}}``.
    """
    signals = ensemble.get("signals") or {}
    return {
        "time": _format_value(_to_unix_seconds(snapshot_date)),
        "open": _format_value(signals.get("ok")),
        "high": _format_value(signals.get("warn")),
        "low": _format_value(signals.get("danger")),
        "close": _format_value(signals.get("neutral")),
        "volume": _format_value(ensemble.get("total_core")),
    }


def _existing_times(path: Path) -> set[str]:
    """Read the ``time`` column from an existing CSV, returning a set of stringified values."""
    if not path.exists():
        return set()
    times: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = iter(reader)
        try:
            header = next(rows)
        except StopIteration:
            return times
        try:
            time_idx = header.index("time")
        except ValueError:
            return times
        for r in rows:
            if not r:
                continue
            if len(r) > time_idx:
                times.add(r[time_idx])
    return times


def append_csv_row(
    path: Path,
    row: dict[str, str],
    header: tuple[str, ...] = CSV_HEADER,
) -> bool:
    """Append a row to the CSV, creating the file with header if missing.

    Returns ``False`` (no-op) if a row with the same ``time`` already exists
    (idempotent — re-running a daily snapshot doesn't dupe).
    Returns ``True`` if appended.
    """
    existing = _existing_times(path)
    if row.get("time", "") in existing:
        return False

    file_existed = path.exists() and path.stat().st_size > 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_existed:
            writer.writerow(header)
        writer.writerow([row.get(col, "") for col in header])
    return True
