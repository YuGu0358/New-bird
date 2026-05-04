"""Pydantic schemas for /api/workflows (Phase 5.6 — visual workflow node editor).

Two layers of validation:

1. The wire schema (``WorkflowUpsertRequest``) is intentionally lax —
   ``definition`` is ``dict[str, Any]`` so the React Flow JSON shape can
   evolve without breaking deployed UIs. We persist whatever the
   frontend sends.

2. The strict schema (``WorkflowDefinition``) is what the engine will
   refuse to run. Routers may opt-in to surface validation errors back
   to the user before persistence. The engine itself also revalidates
   per-node ``data`` shapes at execution time.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _-]+$")
_MIN_SCHEDULE_SECONDS = 60


NodeType = Literal["data-fetch", "indicator", "signal", "risk-check", "order"]


class WorkflowNodePosition(BaseModel):
    """Optional UI hint — backend ignores it but round-trips it intact."""

    model_config = ConfigDict(extra="allow")

    x: float = 0.0
    y: float = 0.0


class WorkflowNode(BaseModel):
    """One node in the React Flow graph."""

    model_config = ConfigDict(extra="allow")

    id: Annotated[str, Field(min_length=1, max_length=64)]
    type: NodeType
    position: WorkflowNodePosition = WorkflowNodePosition()
    data: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    """One edge linking two nodes by id."""

    model_config = ConfigDict(extra="allow")

    id: Annotated[str, Field(min_length=1, max_length=64)]
    source: Annotated[str, Field(min_length=1, max_length=64)]
    target: Annotated[str, Field(min_length=1, max_length=64)]


class WorkflowDefinition(BaseModel):
    """Strict validation: edges must reference declared nodes."""

    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]

    @model_validator(mode="after")
    def _validate_edges_reference_nodes(self) -> "WorkflowDefinition":
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("duplicate node ids in workflow definition")
        for edge in self.edges:
            if edge.source not in ids:
                raise ValueError(f"edge {edge.id} source {edge.source!r} not found")
            if edge.target not in ids:
                raise ValueError(f"edge {edge.id} target {edge.target!r} not found")
        return self


class WorkflowUpsertRequest(BaseModel):
    """Request body for PUT /api/workflows.

    ``definition`` is kept loose (``dict[str, Any]``) so the wire format
    can carry React Flow extensions; the engine validates structure on
    execute. ``schedule_seconds`` must be at least 60s when set — APS
    won't enforce that and 0/1s would hammer the runtime.
    """

    name: Annotated[str, Field(min_length=1, max_length=120)]
    definition: dict[str, Any]
    schedule_seconds: int | None = None
    is_active: bool = False

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "name must contain only letters, digits, spaces, "
                "underscores, or hyphens"
            )
        return value

    @field_validator("schedule_seconds")
    @classmethod
    def _validate_schedule(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < _MIN_SCHEDULE_SECONDS:
            raise ValueError(
                f"schedule_seconds must be >= {_MIN_SCHEDULE_SECONDS} when set"
            )
        return value


class WorkflowView(BaseModel):
    """Single workflow row returned by GET / PUT."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    definition: dict[str, Any]
    schedule_seconds: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowView]


class WorkflowNodeRunView(BaseModel):
    """One node's run output (wire shape for ``NodeResult``)."""

    node_id: str
    node_type: str
    output: dict[str, Any]
    error: str | None = None


class WorkflowRunView(BaseModel):
    """POST /run response shape."""

    succeeded: bool
    duration_ms: int
    nodes: list[WorkflowNodeRunView]
    final_output: dict[str, Any]
