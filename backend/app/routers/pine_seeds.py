"""TradingView pine-seeds workspace endpoints.

GET  /api/pine-seeds/status   workspace + repo URL + last-export metadata
POST /api/pine-seeds/export   build CSVs/JSONs (optionally git-publish)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app import runtime_settings
from app.db.engine import DATA_DIR
from app.dependencies import service_error
from app.models.pine_seeds import (
    PineSeedsExportRequest,
    PineSeedsExportResponse,
    PineSeedsStatusResponse,
)
from app.services import pine_seeds_publisher, pine_seeds_service

router = APIRouter(prefix="/api/pine-seeds", tags=["pine-seeds"])


def _resolve_workspace() -> Path:
    """Pick the workspace dir from PINE_SEEDS_DIR or fall back to <DATA_DIR>/pine_seeds."""
    configured = (runtime_settings.get_setting("PINE_SEEDS_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    base = DATA_DIR.strip() if DATA_DIR else ""
    if base:
        return Path(base).expanduser() / "pine_seeds"
    # Fallback for local dev: alongside the SQLite DB.
    return Path(__file__).resolve().parents[2] / "pine_seeds"


def _read_tickers_emitted(workspace: Path) -> list[str]:
    cats_path = workspace / "seeds_categories.json"
    if not cats_path.exists():
        return []
    try:
        payload = json.loads(cats_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — malformed file shouldn't crash the status endpoint
        return []
    tickers: list[str] = []
    for value in payload.values() if isinstance(payload, dict) else []:
        if isinstance(value, list):
            tickers.extend(str(item) for item in value)
    return tickers


def _last_export_at(workspace: Path) -> datetime | None:
    data_dir = workspace / "data"
    if not data_dir.exists():
        return None
    mtimes = [p.stat().st_mtime for p in data_dir.iterdir() if p.is_file()]
    if not mtimes:
        return None
    return datetime.fromtimestamp(max(mtimes), tz=timezone.utc)


@router.get("/status", response_model=PineSeedsStatusResponse)
async def get_status() -> PineSeedsStatusResponse:
    try:
        workspace = _resolve_workspace()
        repo_url = (runtime_settings.get_setting("PINE_SEEDS_REPO_URL", "") or "").strip()
        tickers = _read_tickers_emitted(workspace) if workspace.exists() else []
        last_at = _last_export_at(workspace) if workspace.exists() else None
    except Exception as exc:  # noqa: BLE001
        raise service_error(exc) from exc

    return PineSeedsStatusResponse(
        workspace=str(workspace) if workspace else None,
        repo_url=repo_url or None,
        last_export_at=last_at,
        tickers_emitted=tickers,
    )


@router.post("/export", response_model=PineSeedsExportResponse)
async def export_snapshot(req: PineSeedsExportRequest) -> PineSeedsExportResponse:
    workspace = _resolve_workspace()
    try:
        summary: dict[str, Any] = await pine_seeds_service.export_snapshot(
            workspace,
            symbols=req.symbols,
            include_macro=req.include_macro,
        )
    except Exception as exc:  # noqa: BLE001
        raise service_error(exc) from exc

    published = False
    publish_reason: str | None = None
    if req.publish:
        try:
            publish_result = await pine_seeds_publisher.publish_workspace(workspace)
        except Exception as exc:  # noqa: BLE001
            raise service_error(exc) from exc
        published = bool(publish_result.get("published"))
        publish_reason = publish_result.get("reason")

    return PineSeedsExportResponse(
        workspace=summary["workspace"],
        tickers_emitted=summary["tickers_emitted"],
        rows_written=summary["rows_written"],
        rows_skipped=summary["rows_skipped"],
        errors=summary["errors"],
        published=published,
        publish_reason=publish_reason,
        generated_at=datetime.now(timezone.utc),
    )
