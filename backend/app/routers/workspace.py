"""Workspace save/load CRUD (Phase 7.3).

Single-user MVP — workspaces are keyed by unique `name` only. Multi-user
namespacing (per-user_id) is a follow-up.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models.workspace import (
    WorkspaceListResponse,
    WorkspaceUpsertRequest,
    WorkspaceView,
)
from app.services import workspace_service

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(session: SessionDep) -> WorkspaceListResponse:
    try:
        items = await workspace_service.list_workspaces(session)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    return WorkspaceListResponse(
        workspaces=[WorkspaceView(**item) for item in items]
    )


@router.get("/{name}", response_model=WorkspaceView)
async def get_workspace(name: str, session: SessionDep) -> WorkspaceView:
    try:
        payload = await workspace_service.get_workspace(session, name)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceView(**payload)


@router.put("", response_model=WorkspaceView)
async def upsert_workspace(
    request: WorkspaceUpsertRequest,
    session: SessionDep,
) -> WorkspaceView:
    """Create-or-replace a workspace by name."""
    try:
        payload = await workspace_service.upsert_workspace(
            session, name=request.name, state=request.state
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return WorkspaceView(**payload)


@router.delete("/{name}", status_code=204)
async def delete_workspace(name: str, session: SessionDep) -> None:
    try:
        deleted = await workspace_service.delete_workspace(session, name)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return None
