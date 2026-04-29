"""Pydantic schemas for /api/workspaces (Phase 7.3 — workspace save/load)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _-]+$")


class WorkspaceUpsertRequest(BaseModel):
    """Request body for PUT /api/workspaces.

    The `state` field is opaque to the backend — whatever JSON-serializable
    blob the UI hands us is round-tripped verbatim on read.
    """

    name: str = Field(min_length=1, max_length=120)
    state: dict[str, Any]

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "name must contain only letters, digits, spaces, "
                "underscores, or hyphens"
            )
        return value


class WorkspaceView(BaseModel):
    """Single workspace row returned by GET / PUT."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    state: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceView]
