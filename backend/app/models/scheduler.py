"""Pydantic schema for /api/scheduler endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ScheduledJobView(BaseModel):
    id: str
    name: str | None = None
    trigger: str           # human-readable, e.g. "interval[0:00:20]"
    next_run_time: datetime | None = None


class ScheduledJobsResponse(BaseModel):
    jobs: list[ScheduledJobView]
