"""Multi-asset screener endpoint — filter / sort / paginate over 55-name universe.

The router is a thin translation layer: query params → ScreenerFilter,
service call, response model. All business logic lives in
`core.screener.compute` and `app.services.screener_service`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import service_error
from app.models.screener import ScreenerResponse
from app.services import screener_service
from core.screener import ScreenerFilter

router = APIRouter(prefix="/api/screener", tags=["screener"])


def _build_filter(
    sector: str | None = None,
    min_market_cap: float | None = None,
    max_market_cap: float | None = None,
    min_pe: float | None = None,
    max_pe: float | None = None,
    min_peg: float | None = None,
    max_peg: float | None = None,
    min_revenue_growth: float | None = None,
    max_revenue_growth: float | None = None,
    min_momentum_3m: float | None = None,
    max_momentum_3m: float | None = None,
) -> ScreenerFilter:
    """FastAPI dependency: collect the 11 filter query params into a ScreenerFilter."""
    return ScreenerFilter(
        sector=sector,
        min_market_cap=min_market_cap,
        max_market_cap=max_market_cap,
        min_pe=min_pe,
        max_pe=max_pe,
        min_peg=min_peg,
        max_peg=max_peg,
        min_revenue_growth=min_revenue_growth,
        max_revenue_growth=max_revenue_growth,
        min_momentum_3m=min_momentum_3m,
        max_momentum_3m=max_momentum_3m,
    )


@router.get("", response_model=ScreenerResponse)
async def screen(
    spec: ScreenerFilter = Depends(_build_filter),
    sort_by: str = "market_cap",
    descending: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> ScreenerResponse:
    """Filter / sort / paginate the screener universe (1h cache)."""
    try:
        payload = await screener_service.search(
            spec=spec,
            sort_by=sort_by,
            descending=descending,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return ScreenerResponse(**payload)


@router.post("/refresh", response_model=ScreenerResponse)
async def refresh_screen(
    spec: ScreenerFilter = Depends(_build_filter),
    sort_by: str = "market_cap",
    descending: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> ScreenerResponse:
    """Force-rebuild the cache, then run the same filter/sort/paginate."""
    try:
        payload = await screener_service.search(
            spec=spec,
            sort_by=sort_by,
            descending=descending,
            page=page,
            page_size=page_size,
            force=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return ScreenerResponse(**payload)
