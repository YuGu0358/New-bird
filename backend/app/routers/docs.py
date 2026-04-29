"""Docs panel endpoints — list + get markdown from the repo's docs/ tree."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.docs import DocDetailResponse, DocListResponse
from app.services import docs_service

router = APIRouter(prefix="/api/docs", tags=["docs"])


@router.get("/list", response_model=DocListResponse)
async def list_docs() -> DocListResponse:
    """Catalogue of every markdown doc under the configured docs root."""
    try:
        payload = await docs_service.list_docs()
    except Exception as exc:
        raise service_error(exc) from exc
    return DocListResponse(**payload)


@router.get("/{slug}", response_model=DocDetailResponse)
async def get_doc(slug: str) -> DocDetailResponse:
    """Raw markdown for a single doc, addressed by its catalogue slug."""
    try:
        payload = await docs_service.get_doc(slug)
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return DocDetailResponse(**payload)
