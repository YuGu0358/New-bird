"""DBnomics adapter router — single-series GET, no auth, no opt-in."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.dbnomics import DBnomicsSeriesResponse
from app.services import dbnomics_service

router = APIRouter(prefix="/api/dbnomics", tags=["dbnomics"])


@router.get(
    "/series/{provider}/{dataset}/{series_id}",
    response_model=DBnomicsSeriesResponse,
)
async def get_series(
    provider: str,
    dataset: str,
    series_id: str,
) -> DBnomicsSeriesResponse:
    """Fetch one DBnomics time-series by `(provider, dataset, series_id)`.

    Errors:
    - 404 when DBnomics has no such series (or returns empty `docs`).
    - 400 on caller-side validation errors raised by the service.
    - 503 (via `service_error`) for any other unexpected failure.
    """
    try:
        payload = await dbnomics_service.get_series(provider, dataset, series_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return DBnomicsSeriesResponse(**payload)
