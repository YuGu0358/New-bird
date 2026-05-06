"""Options-chain analytics endpoints — GEX, walls, max pain, expiry focus.

Distinct from /api/quantlib (which is single-option pricing). Path-prefixed
under /api/options-chain to avoid colliding with the existing quantlib router
or with future broker-side options endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.options_chain import (
    ExpiryFocusResponse,
    FridayScanResponse,
    GexSummaryResponse,
    IVSurfaceResponse,
    OIFloatResponse,
    SqueezeScoreResponse,
    StructureReadResponse,
    StructureSnapshotsResponse,
    StructureSnapshotView,
    StructureTrackRecordResponse,
    WallClustersResponse,
)
from app.services import options_chain_service, structure_track_record_service

router = APIRouter(prefix="/api/options-chain", tags=["options-chain"])


@router.get("/{ticker}", response_model=GexSummaryResponse)
async def get_chain_gex(ticker: str, max_expiries: int = 6) -> GexSummaryResponse:
    try:
        payload = await options_chain_service.get_gex_summary(
            ticker, max_expiries=max(1, min(max_expiries, 12))
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return GexSummaryResponse(**payload)


@router.post("/{ticker}/refresh", response_model=GexSummaryResponse)
async def refresh_chain_gex(ticker: str, max_expiries: int = 6) -> GexSummaryResponse:
    try:
        payload = await options_chain_service.get_gex_summary(
            ticker, max_expiries=max(1, min(max_expiries, 12)), force=True
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return GexSummaryResponse(**payload)


@router.get("/{ticker}/friday-scan", response_model=FridayScanResponse)
async def get_friday_scan(
    ticker: str,
    expiry: str | None = None,
    max_expiries: int = 6,
) -> FridayScanResponse:
    """Pinning-probability score for the next Friday (or specified expiry).

    `expiry` is optional — when omitted we pick the next Friday found in the
    chain (or the next available expiry within 7 days).
    """
    try:
        payload = await options_chain_service.get_friday_scan(
            ticker, expiry, max_expiries=max(1, min(max_expiries, 12))
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No chain data available for {ticker.upper()}",
        )
    return FridayScanResponse(**payload)


@router.get("/{ticker}/squeeze", response_model=SqueezeScoreResponse)
async def get_squeeze(ticker: str, max_expiries: int = 6) -> SqueezeScoreResponse:
    """4-factor squeeze score: IV rank + OI concentration + PC ratio + short interest."""
    try:
        payload = await options_chain_service.get_squeeze_score(
            ticker, max_expiries=max(1, min(max_expiries, 12))
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No chain data available for {ticker.upper()}",
        )
    return SqueezeScoreResponse(**payload)


@router.get("/{ticker}/structure", response_model=StructureReadResponse)
async def get_structure(ticker: str, max_expiries: int = 6) -> StructureReadResponse:
    """Structural pattern: 5 signals -> 4 patterns (+ UNCLEAR fallback)."""
    try:
        payload = await options_chain_service.get_structure_read(
            ticker, max_expiries=max(1, min(max_expiries, 12))
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No chain data available for {ticker.upper()}",
        )
    return StructureReadResponse(**payload)


@router.get("/{ticker}/oi-float", response_model=OIFloatResponse)
async def get_oi_float(ticker: str, max_expiries: int = 6) -> OIFloatResponse:
    """Notional + delta-adjusted OI as a fraction of the public float."""
    try:
        payload = await options_chain_service.get_oi_float(
            ticker, max_expiries=max(1, min(max_expiries, 12))
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No chain data available for {ticker.upper()}",
        )
    return OIFloatResponse(**payload)


@router.get("/{ticker}/clusters", response_model=WallClustersResponse)
async def get_wall_clusters(
    ticker: str,
    max_expiries: int = 6,
    threshold_pct: float = 0.20,
    top_n: int = 2,
) -> WallClustersResponse:
    """Tenor-bucketed wall clusters: 0-7 / 8-30 / 31+ DTE buckets."""
    try:
        payload = await options_chain_service.get_wall_clusters(
            ticker,
            max_expiries=max(1, min(max_expiries, 12)),
            threshold_pct=max(0.0, min(threshold_pct, 1.0)),
            top_n=max(1, min(top_n, 5)),
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No chain data available for {ticker.upper()}",
        )
    return WallClustersResponse(**payload)


@router.get("/{ticker}/iv-surface", response_model=IVSurfaceResponse)
async def get_iv_surface(ticker: str, max_expiries: int = 6) -> IVSurfaceResponse:
    """Strike x expiry IV grid + per-expiry term-structure summary."""
    try:
        payload = await options_chain_service.get_iv_surface(
            ticker, max_expiries=max(1, min(max_expiries, 12))
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No chain data available for {ticker.upper()}",
        )
    return IVSurfaceResponse(**payload)


@router.get("/{ticker}/expiry/{expiry}", response_model=ExpiryFocusResponse)
async def get_expiry_focus(
    ticker: str,
    expiry: str,
    max_expiries: int = 6,
    top_n: int = 5,
) -> ExpiryFocusResponse:
    """Drill-in for one expiry: ATM IV, expected move, top OI strikes."""
    try:
        payload = await options_chain_service.get_expiry_focus(
            ticker,
            expiry,
            max_expiries=max(1, min(max_expiries, 12)),
            top_n=max(1, min(top_n, 10)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No contracts found for {ticker.upper()} expiry {expiry}",
        )
    return ExpiryFocusResponse(**payload)


# --- Structure-read thesis tracker ---------------------------------------


@router.post(
    "/{ticker}/structure/capture",
    response_model=StructureSnapshotView,
)
async def capture_structure_snapshot(
    ticker: str, horizon_days: int = 5
) -> StructureSnapshotView:
    """Persist today's structure-read so its thesis can be scored after
    ``horizon_days`` trading days. Idempotent on (capture_date, ticker,
    horizon_days) — first call of the day wins.
    """
    if horizon_days <= 0 or horizon_days > 30:
        raise HTTPException(
            status_code=400, detail="horizon_days must be in (0, 30]"
        )
    try:
        row = await structure_track_record_service.capture_snapshot(
            ticker, horizon_days=horizon_days
        )
    except Exception as exc:
        raise service_error(exc) from exc
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Structure read unavailable for {ticker.upper()}",
        )
    return StructureSnapshotView.model_validate(row)


@router.post("/track-record/evaluate")
async def evaluate_pending_snapshots(max_rows: int = 200) -> dict[str, int]:
    """Score any snapshots whose horizon has passed but were still
    ``pending``. Safe to call repeatedly — only touches pending rows."""
    capped = max(1, min(max_rows, 1000))
    try:
        return await structure_track_record_service.evaluate_pending(
            max_rows=capped
        )
    except Exception as exc:
        raise service_error(exc) from exc


@router.get(
    "/track-record",
    response_model=StructureTrackRecordResponse,
)
async def get_track_record(
    horizon_days: int | None = None,
) -> StructureTrackRecordResponse:
    """Aggregated hit-rate per pattern. Pass ``horizon_days`` to filter."""
    payload = await structure_track_record_service.aggregate_track_record(
        horizon_days=horizon_days
    )
    return StructureTrackRecordResponse(**payload)


@router.get(
    "/track-record/snapshots",
    response_model=StructureSnapshotsResponse,
)
async def list_track_record_snapshots(
    ticker: str | None = None, limit: int = 100
) -> StructureSnapshotsResponse:
    """Recent snapshots — most recent first. Filter by ticker if given."""
    items = await structure_track_record_service.list_recent_snapshots(
        ticker=ticker, limit=limit
    )
    return StructureSnapshotsResponse(
        items=[StructureSnapshotView.model_validate(it) for it in items]
    )
