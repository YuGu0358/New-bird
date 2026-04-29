"""Scheduler observability endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app import scheduler as app_scheduler
from app.dependencies import service_error
from app.models.scheduler import ScheduledJobsResponse, ScheduledJobView

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/jobs", response_model=ScheduledJobsResponse)
async def list_jobs() -> ScheduledJobsResponse:
    """List every job currently registered with the application scheduler."""
    try:
        sched = app_scheduler.get_scheduler()
        if sched is None:
            return ScheduledJobsResponse(jobs=[])
        jobs = [
            ScheduledJobView(
                id=job.id,
                name=job.name,
                trigger=str(job.trigger),
                next_run_time=job.next_run_time,
            )
            for job in sched.get_jobs()
        ]
        return ScheduledJobsResponse(jobs=jobs)
    except Exception as exc:  # noqa: BLE001
        raise service_error(exc) from exc
