"""Sector rotation endpoints — 11 GICS SPDR ETFs returns + ranks."""
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import service_error
from app.models.sector_rotation import SectorRotationResponse
from app.services import sector_rotation_service

router = APIRouter(prefix="/api/sectors", tags=["sectors"])


@router.get("/rotation", response_model=SectorRotationResponse)
async def get_rotation() -> SectorRotationResponse:
    """1d / 5d / 1m / 3m / YTD returns + ranks for the 11 sector SPDRs."""
    try:
        payload = await sector_rotation_service.get_sector_rotation()
    except Exception as exc:
        raise service_error(exc) from exc
    return SectorRotationResponse(**payload)


@router.post("/rotation/refresh", response_model=SectorRotationResponse)
async def refresh_rotation() -> SectorRotationResponse:
    """Force-refresh the rotation cache."""
    try:
        payload = await sector_rotation_service.get_sector_rotation(force=True)
    except Exception as exc:
        raise service_error(exc) from exc
    return SectorRotationResponse(**payload)
