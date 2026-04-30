"""Visual workflow node-editor CRUD + run + enable/disable (Phase 5.6).

Single-user MVP — workflows are keyed by unique ``name`` only.
``definition`` is the React Flow JSON shape; the backend persists it
verbatim and only validates structure when the engine runs.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import AdminTokenDep, SessionDep, service_error
from app.models.workflow import (
    WorkflowListResponse,
    WorkflowRunView,
    WorkflowUpsertRequest,
    WorkflowView,
)
from app.services import workflow_service

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(session: SessionDep) -> WorkflowListResponse:
    try:
        items = await workflow_service.list_workflows(session)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    return WorkflowListResponse(
        workflows=[WorkflowView(**item) for item in items]
    )


@router.get("/{name}", response_model=WorkflowView)
async def get_workflow(name: str, session: SessionDep) -> WorkflowView:
    try:
        payload = await workflow_service.get_workflow(session, name)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowView(**payload)


@router.put("", response_model=WorkflowView, dependencies=[AdminTokenDep])
async def upsert_workflow(
    request: WorkflowUpsertRequest,
    session: SessionDep,
) -> WorkflowView:
    """Create-or-replace a workflow by name."""
    try:
        payload = await workflow_service.upsert_workflow(
            session,
            name=request.name,
            definition=request.definition,
            schedule_seconds=request.schedule_seconds,
            is_active=request.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return WorkflowView(**payload)


@router.delete("/{name}", status_code=204, dependencies=[AdminTokenDep])
async def delete_workflow(name: str, session: SessionDep) -> None:
    try:
        deleted = await workflow_service.delete_workflow(session, name)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return None


@router.post("/{name}/run", response_model=WorkflowRunView, dependencies=[AdminTokenDep])
async def run_workflow(name: str, session: SessionDep) -> WorkflowRunView:
    try:
        payload = await workflow_service.run_workflow_by_name(session, name)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowRunView(**payload)


@router.post("/{name}/enable", response_model=WorkflowView, dependencies=[AdminTokenDep])
async def enable_workflow(name: str, session: SessionDep) -> WorkflowView:
    try:
        payload = await workflow_service.enable_workflow(session, name)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowView(**payload)


@router.post("/{name}/disable", response_model=WorkflowView, dependencies=[AdminTokenDep])
async def disable_workflow(name: str, session: SessionDep) -> WorkflowView:
    try:
        payload = await workflow_service.disable_workflow(session, name)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowView(**payload)
