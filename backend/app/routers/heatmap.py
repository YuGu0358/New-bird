"""Heatmap endpoints — symbol-level tiles + 11-sector aggregate."""
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import service_error
from app.models.heatmap import (
    HeatmapSectorsResponse,
    HeatmapSymbolsResponse,
)
from app.services import heatmap_service

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])


@router.get("/symbols", response_model=HeatmapSymbolsResponse)
async def get_symbol_tiles() -> HeatmapSymbolsResponse:
    """Per-symbol heatmap tiles (55 names across 11 GICS sectors)."""
    try:
        payload = await heatmap_service.get_symbol_heatmap()
    except Exception as exc:
        raise service_error(exc) from exc
    return HeatmapSymbolsResponse(**payload)


@router.get("/sectors", response_model=HeatmapSectorsResponse)
async def get_sector_aggregate() -> HeatmapSectorsResponse:
    """Sector-level aggregate (market-cap-weighted change)."""
    try:
        payload = await heatmap_service.get_sector_heatmap()
    except Exception as exc:
        raise service_error(exc) from exc
    return HeatmapSectorsResponse(**payload)
