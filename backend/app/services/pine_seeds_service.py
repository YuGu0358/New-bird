"""Orchestration for pine-seeds workspace exports.

Builds a TradingView pine-seeds-compatible directory tree from live Newbird
signals (options walls, PE channel, macro ensemble). Pure stdlib + the row
builders in ``core.pine_seeds``; downstream callers (CLI, scheduler) just
hand us a target directory.

The CSV file naming follows the pine-seeds spec exactly:
``NEWBIRD_<SYM>_LEVELS, 1D.csv`` — note the literal space after the comma.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from app import runtime_settings
from app.services import macro_service, options_chain_service, valuation_service
from core.pine_seeds import (
    append_csv_row,
    build_levels_row,
    build_macro_row,
    build_val_row,
    symbol_info_for,
)

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ", "NVDA", "AAPL")


def _resolve_symbols(symbols: list[str] | None) -> list[str]:
    if symbols is not None:
        return [s.upper() for s in symbols if s and s.strip()]

    raw = runtime_settings.get_setting("PINE_SEEDS_WATCHLIST", "") or ""
    parts = [p.strip().upper() for p in raw.split(",") if p and p.strip()]
    if parts:
        return parts
    return list(DEFAULT_SYMBOLS)


def _csv_path(workspace: Path, ticker: str, kind: str) -> Path:
    """Pine-seeds expects ``NEWBIRD_<SYM>_<KIND>, 1D.csv`` (space after comma)."""
    if kind == "MACRO":
        name = "NEWBIRD_MACRO_ENSEMBLE, 1D.csv"
    else:
        name = f"NEWBIRD_{ticker}_{kind}, 1D.csv"
    return workspace / "data" / name


def _info_path(workspace: Path, ticker: str, kind: str) -> Path:
    if kind == "MACRO":
        return workspace / "symbol_info" / "NEWBIRD_MACRO_ENSEMBLE.json"
    return workspace / "symbol_info" / f"NEWBIRD_{ticker}_{kind}.json"


def _full_symbol(ticker: str, kind: str) -> str:
    if kind == "MACRO":
        return "NEWBIRD_MACRO_ENSEMBLE"
    return f"NEWBIRD_{ticker}_{kind}"


def _write_symbol_info(workspace: Path, ticker: str, kind: str) -> None:
    """Write the symbol_info JSON if missing."""
    path = _info_path(workspace, ticker, kind)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    info = symbol_info_for(ticker, kind)  # type: ignore[arg-type]
    path.write_text(json.dumps(info, indent=2), encoding="utf-8")


def _val_has_signal(pe_channel: dict) -> bool:
    """At least one band non-None → emit a row."""
    for key in ("fair_p25", "fair_p95", "fair_p5", "fair_p50"):
        if pe_channel.get(key) is not None:
            return True
    return False


async def export_snapshot(
    workspace: Path,
    *,
    symbols: list[str] | None = None,
    include_macro: bool = True,
) -> dict[str, Any]:
    """Build the full pine-seeds workspace under ``workspace``.

    See module docstring for the file-naming convention.
    """
    workspace = Path(workspace)
    (workspace / "data").mkdir(parents=True, exist_ok=True)
    (workspace / "symbol_info").mkdir(parents=True, exist_ok=True)

    resolved_symbols = _resolve_symbols(symbols)
    snapshot_date = date.today()

    tickers_emitted: list[str] = []
    rows_written = 0
    rows_skipped = 0
    errors: list[dict[str, str]] = []

    for symbol in resolved_symbols:
        # --- LEVELS ---
        try:
            gex = await options_chain_service.get_gex_summary(symbol)
        except Exception as exc:  # noqa: BLE001 — upstream outages mustn't kill the batch
            logger.warning("pine-seeds LEVELS skip %s: %s", symbol, exc)
            errors.append({"ticker": symbol, "kind": "LEVELS", "error": str(exc)})
        else:
            try:
                row = build_levels_row(snapshot_date=snapshot_date, gex_summary=gex)
                appended = append_csv_row(_csv_path(workspace, symbol, "LEVELS"), row)
                _write_symbol_info(workspace, symbol, "LEVELS")
                full = _full_symbol(symbol, "LEVELS")
                if appended:
                    rows_written += 1
                else:
                    rows_skipped += 1
                if full not in tickers_emitted:
                    tickers_emitted.append(full)
            except Exception as exc:  # noqa: BLE001
                logger.warning("pine-seeds LEVELS write %s: %s", symbol, exc)
                errors.append({"ticker": symbol, "kind": "LEVELS", "error": str(exc)})

        # --- VAL ---
        try:
            pe = await valuation_service.fetch_pe_channel(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pine-seeds VAL skip %s: %s", symbol, exc)
            errors.append({"ticker": symbol, "kind": "VAL", "error": str(exc)})
        else:
            if not _val_has_signal(pe):
                logger.info("pine-seeds VAL %s: no PE signal — skipping row", symbol)
            else:
                try:
                    row = build_val_row(snapshot_date=snapshot_date, pe_channel=pe)
                    appended = append_csv_row(_csv_path(workspace, symbol, "VAL"), row)
                    _write_symbol_info(workspace, symbol, "VAL")
                    full = _full_symbol(symbol, "VAL")
                    if appended:
                        rows_written += 1
                    else:
                        rows_skipped += 1
                    if full not in tickers_emitted:
                        tickers_emitted.append(full)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("pine-seeds VAL write %s: %s", symbol, exc)
                    errors.append({"ticker": symbol, "kind": "VAL", "error": str(exc)})

    # --- MACRO ---
    if include_macro:
        try:
            dashboard = await macro_service.get_dashboard()
        except Exception as exc:  # noqa: BLE001
            logger.warning("pine-seeds MACRO skip: %s", exc)
            errors.append({"ticker": "MACRO", "kind": "MACRO", "error": str(exc)})
        else:
            try:
                ensemble = dashboard.get("ensemble") or {}
                row = build_macro_row(snapshot_date=snapshot_date, ensemble=ensemble)
                appended = append_csv_row(_csv_path(workspace, "MACRO", "MACRO"), row)
                _write_symbol_info(workspace, "MACRO", "MACRO")
                full = _full_symbol("MACRO", "MACRO")
                if appended:
                    rows_written += 1
                else:
                    rows_skipped += 1
                if full not in tickers_emitted:
                    tickers_emitted.append(full)
            except Exception as exc:  # noqa: BLE001
                logger.warning("pine-seeds MACRO write: %s", exc)
                errors.append({"ticker": "MACRO", "kind": "MACRO", "error": str(exc)})

    # --- seeds_categories.json ---
    cats_path = workspace / "seeds_categories.json"
    cats_payload = {"Newbird Signals": list(tickers_emitted)}
    cats_path.write_text(json.dumps(cats_payload, indent=2), encoding="utf-8")

    return {
        "workspace": str(workspace),
        "tickers_emitted": list(tickers_emitted),
        "rows_written": rows_written,
        "rows_skipped": rows_skipped,
        "errors": errors,
    }
