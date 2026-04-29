"""GlassNode on-chain metrics endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.onchain import OnChainMetricResponse
from app.services import glassnode_service

router = APIRouter(prefix="/api/onchain", tags=["onchain"])


@router.get(
    "/metrics/{asset}/{metric_path:path}",
    response_model=OnChainMetricResponse,
)
async def get_metric(
    asset: str,
    metric_path: str,
    since: int | None = None,
    until: int | None = None,
    interval: str | None = None,
) -> OnChainMetricResponse:
    """GlassNode on-chain metric series — opt-in via GLASSNODE_ENABLED.

    `metric_path` accepts slash-separated GlassNode paths (e.g.
    `market/price_usd_close`, `addresses/active_count`).
    """
    try:
        payload = await glassnode_service.get_metric(
            asset.upper(),
            metric_path,
            since=since,
            until=until,
            interval=interval,
        )
    except RuntimeError as exc:
        if "disabled" in str(exc).lower():
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if "key is missing" in str(exc).lower():
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        raise service_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return OnChainMetricResponse(**payload)
