"""Coordinates the full daily Factor Forge run: data -> universe -> news -> evolution.

Public surface:
- ``run_full_pipeline()`` — end-to-end: refresh bars, recompute the active
  universe for ``target_date``, refresh per-symbol metadata, pull news
  features, train the fitness predictor, run the two-stage evolution,
  persist a ``FactorEvolutionRun`` row.
- ``schedule_default_jobs()`` — register the daily cron job (16:35 ET /
  21:35 UTC) on the shared APScheduler. Idempotent and tolerant of a
  missing scheduler.

The router uses ``_create_run`` directly when a manual trigger needs a
run id up front; the placeholder row is then deleted before
``run_full_pipeline`` creates its own row, so each pipeline invocation
ends up with exactly one row.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.engine import AsyncSessionLocal
from app.db.tables import FactorEvolutionRun
from app.services import (
    factor_data_service,
    factor_fitness_predictor,
    factor_gp_service,
    factor_meta_service,
    factor_news_service,
)

try:  # FF-E may not be wired yet — degrade gracefully if its imports fail.
    from app.services import factor_llm_mutation_service as llm_mut  # noqa: F401
except Exception:  # pragma: no cover - defensive
    llm_mut = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 16:35 ET ~= 21:35 UTC during EST. Good enough as MVP — DST drift is
# acceptable for an analytical job that just needs to run once per day.
_DAILY_JOB_ID = "factor_forge_daily"
_DAILY_HOUR_UTC = 21
_DAILY_MINUTE_UTC = 35
_NEWS_TOP_N = 100
_PREDICTOR_MIN_RECORDS = 30
_ERROR_TRUNCATE = 1024


async def _create_run() -> int:
    """Insert a new run row in the ``running`` state and return its id."""
    async with AsyncSessionLocal() as session:
        run = FactorEvolutionRun()
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return int(run.id)


async def _update_run(run_id: int, **fields: Any) -> None:
    """Patch the run row identified by ``run_id`` with the given fields."""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FactorEvolutionRun).where(FactorEvolutionRun.id == run_id)
            )
        ).scalar_one_or_none()
        if row is None:
            logger.warning("Factor run %d not found for update", run_id)
            return
        for key, value in fields.items():
            setattr(row, key, value)
        await session.commit()


def _stats_dict(stats: Any) -> dict[str, Any]:
    """Best-effort coerce a GenerationStats-like object into a JSON-able dict."""
    if is_dataclass(stats):
        return asdict(stats)
    if hasattr(stats, "__dict__"):
        return dict(stats.__dict__)
    return {"value": str(stats)}


def _max_best_fitness(stage_stats: list[Any]) -> float | None:
    values = [s.best_fitness for s in stage_stats if s.best_fitness is not None]
    return max(values) if values else None


def _sum_persisted(stage_stats: list[Any]) -> int:
    return int(sum(getattr(s, "new_persisted", 0) for s in stage_stats))


async def run_full_pipeline(*, target_date: date | None = None) -> int:
    """Execute the full daily Factor Forge pipeline.

    Returns the ``FactorEvolutionRun.id`` so callers can poll status. Any
    exception inside the pipeline is captured and recorded on the row as
    ``status='failed'`` with a truncated error message — the function
    itself does not re-raise.
    """
    target = target_date or date.today()
    run_id = await _create_run()
    try:
        logger.info("[Factor Forge run %d] starting for %s", run_id, target)

        # Stage 0: refresh inputs.
        await factor_data_service.update_daily_bars()
        await factor_data_service.update_active_universe(target)
        symbols = await factor_data_service.get_active_universe(target, top_n=_NEWS_TOP_N)
        await factor_meta_service.refresh_symbol_meta(symbols)
        await factor_news_service.update_news_features(symbols, target)

        # Stage 0.5: cheap fitness predictor (skips when library is too small).
        predictor = await factor_fitness_predictor.train_from_library(
            min_records=_PREDICTOR_MIN_RECORDS
        )
        pre_filter = predictor.predict if predictor.is_trained else None

        # Stage 1+2: two-stage genetic evolution.
        result = await factor_gp_service.run_two_stage_evolution(
            end=target,
            pre_score_filter=pre_filter,
        )

        stage1_best = _max_best_fitness(list(result.stage_1_stats))
        stage2_best = _max_best_fitness(list(result.stage_2_stats))
        total_persisted = _sum_persisted(list(result.stage_1_stats)) + _sum_persisted(
            list(result.stage_2_stats)
        )

        stats_payload = {
            "stage1": [_stats_dict(s) for s in result.stage_1_stats],
            "stage2": [_stats_dict(s) for s in result.stage_2_stats],
            "survivors": list(result.survivors),
        }

        await _update_run(
            run_id,
            completed_at=datetime.now(timezone.utc),
            status="completed",
            stage1_best=stage1_best,
            stage2_best=stage2_best,
            total_persisted=total_persisted,
            stats_json=json.dumps(stats_payload, default=str),
        )
        logger.info(
            "[Factor Forge run %d] done: persisted=%d s2_best=%s",
            run_id,
            total_persisted,
            stage2_best,
        )
    except Exception as exc:  # noqa: BLE001 — pipeline is the top of the call stack
        logger.exception("[Factor Forge run %d] failed", run_id)
        await _update_run(
            run_id,
            completed_at=datetime.now(timezone.utc),
            status="failed",
            error=str(exc)[:_ERROR_TRUNCATE],
        )
    return run_id


async def _scheduled_runner() -> None:
    """APScheduler entrypoint — runs the pipeline for today's date."""
    await run_full_pipeline()


async def schedule_default_jobs() -> None:
    """Register the daily Factor Forge cron job. Safe to call repeatedly.

    Tolerant of a missing scheduler — returns silently when the
    application scheduler hasn't been started yet (e.g., in tests that
    skip the lifespan).
    """
    from app import scheduler as app_scheduler

    sched = app_scheduler.get_scheduler()
    if sched is None:
        logger.info("Scheduler not running; skipping factor_forge_daily registration.")
        return
    sched.add_job(
        _scheduled_runner,
        trigger="cron",
        id=_DAILY_JOB_ID,
        hour=_DAILY_HOUR_UTC,
        minute=_DAILY_MINUTE_UTC,
        replace_existing=True,
    )
    logger.info(
        "Registered scheduled job %s (daily at %02d:%02d UTC)",
        _DAILY_JOB_ID,
        _DAILY_HOUR_UTC,
        _DAILY_MINUTE_UTC,
    )
