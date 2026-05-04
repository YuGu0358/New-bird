"""Pydantic schemas for the ``workflow_runs`` audit log.

Read-only — workflow_runs rows are written by the service-layer audit
hook in ``workflow_service._record_workflow_run`` and exposed via
``GET /api/workflows/{name}/runs``.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WorkflowRunView(BaseModel):
    """One audit row — represents one paper-order dispatch."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_name: str
    symbol: str | None = None
    side: str | None = None
    qty: float | None = None
    notional: float | None = None
    accepted: bool = False
    broker: str | None = None
    reason: str | None = None
    dispatched_at: datetime


class WorkflowRunsResponse(BaseModel):
    items: list[WorkflowRunView]
