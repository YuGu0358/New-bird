"""Factor Forge HTTP API.

Thin layer over ``factor_vector_store`` (library reads),
``factor_pipeline`` (evolution runs), and the ``factor_daily_active_universe``
table (universe snapshot reads). The frontend's Factor Forge dashboard
binds directly to the response shapes defined here.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from app.db.engine import AsyncSessionLocal
from app.db.tables import (
    DailyActiveUniverse,
    DailyBar,
    FactorEvolutionRun,
    FactorGenerationStat,
    FactorPopulationState,
    FactorRecord,
)
from app.models.factors import (
    ActiveUniverseItem,
    ActiveUniverseResponse,
    EvolutionControlResponse,
    EvolutionStatusResponse,
    FactorEvolutionRunsResponse,
    FactorEvolutionRunView,
    FactorLibraryResponse,
    FactorRecordView,
    GenerationHistoryResponse,
    GenerationStatView,
    LandscapePoint,
    LandscapeResponse,
    PopulationSlotView,
    PopulationSnapshotResponse,
    QARequest,
    QAResponse,
    QAToolCall,
    RecommendationView,
    RecommendationsResponse,
    TrajectoriesResponse,
    TrajectoryNodeView,
)
from app.services import (
    factor_landscape_service,
    factor_pipeline,
    factor_qa_service,
    factor_quanta_service,
    factor_vector_store,
    today_recommendations_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/factors", tags=["factors"])


@router.get("/library", response_model=FactorLibraryResponse)
async def list_library(
    limit: int = 100,
    sort_by: str = "fitness",
    min_fitness: float | None = None,
    include_quarantined: bool = False,
) -> FactorLibraryResponse:
    """Return the top factors from the vector store, sorted by ``sort_by``.

    By default quarantined (suspicious) factors are excluded — pass
    ``include_quarantined=true`` to see them too.
    """
    items = await factor_vector_store.list_factors(
        limit=limit,
        sort_by=sort_by,
        min_fitness=min_fitness,
        include_quarantined=include_quarantined,
    )
    return FactorLibraryResponse(
        items=[FactorRecordView.model_validate(item) for item in items]
    )


@router.get("/library/{factor_id}", response_model=FactorRecordView)
async def get_factor(factor_id: int) -> FactorRecordView:
    """Fetch a single factor record by id."""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FactorRecord).where(FactorRecord.id == factor_id)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="factor not found")
    return FactorRecordView.model_validate(row)


@router.get("/active-universe", response_model=ActiveUniverseResponse)
async def get_active_universe(
    query_date: date_cls | None = None,
    top_n: int = 100,
) -> ActiveUniverseResponse:
    """Return today's (or ``query_date``'s) ranked active universe.

    When no rows exist for the requested date (weekends, holidays, or
    pre-market on a fresh day where Alpaca hasn't delivered EOD bars
    yet), fall back to the most recent stored universe ≤ target so the
    UI never shows a stale-but-empty page after a successful refresh.
    """
    from sqlalchemy import func as _func

    target = query_date or date_cls.today()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyActiveUniverse)
                .where(DailyActiveUniverse.date == target)
                .order_by(DailyActiveUniverse.rank)
                .limit(top_n)
            )
        ).scalars().all()
        if not rows:
            most_recent = (
                await session.execute(
                    select(_func.max(DailyActiveUniverse.date)).where(
                        DailyActiveUniverse.date <= target
                    )
                )
            ).scalar()
            if most_recent is not None:
                target = most_recent
                rows = (
                    await session.execute(
                        select(DailyActiveUniverse)
                        .where(DailyActiveUniverse.date == target)
                        .order_by(DailyActiveUniverse.rank)
                        .limit(top_n)
                    )
                ).scalars().all()
    items = [
        ActiveUniverseItem(
            rank=r.rank,
            symbol=r.symbol,
            activity_score=r.activity_score,
            dollar_volume=r.dollar_volume,
        )
        for r in rows
    ]
    return ActiveUniverseResponse(date=target, items=items)


@router.get("/runs", response_model=FactorEvolutionRunsResponse)
async def list_runs(limit: int = 20) -> FactorEvolutionRunsResponse:
    """Most-recent evolution runs first."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorEvolutionRun)
                .order_by(desc(FactorEvolutionRun.started_at))
                .limit(limit)
            )
        ).scalars().all()
    items = [FactorEvolutionRunView.model_validate(r) for r in rows]
    return FactorEvolutionRunsResponse(items=items)


@router.get("/runs/{run_id}", response_model=FactorEvolutionRunView)
async def get_run(run_id: int) -> FactorEvolutionRunView:
    """Fetch a single run's status / stats."""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FactorEvolutionRun).where(FactorEvolutionRun.id == run_id)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return FactorEvolutionRunView.model_validate(row)


@router.get("/evolution/status", response_model=EvolutionStatusResponse)
async def get_evolution_status() -> EvolutionStatusResponse:
    """Live status of the continuous Factor Forge evolution loop."""
    payload = await factor_pipeline.evolution_status()
    return EvolutionStatusResponse(**payload)


@router.post("/evolution/start", response_model=EvolutionControlResponse)
async def start_evolution() -> EvolutionControlResponse:
    """Start the continuous evolution loop (idempotent)."""
    msg = await factor_pipeline.start_loop()
    return EvolutionControlResponse(is_running=True, message=msg)


@router.post("/evolution/stop", response_model=EvolutionControlResponse)
async def stop_evolution() -> EvolutionControlResponse:
    """Stop the continuous evolution loop (idempotent)."""
    msg = await factor_pipeline.stop_loop()
    return EvolutionControlResponse(is_running=False, message=msg)


@router.post("/admin/refresh-data")
async def admin_refresh_data() -> dict[str, str]:
    """One-shot trigger for the daily data-refresh job.

    Useful right after a fresh deploy where the persistent volume is
    empty — fills factor_daily_bars + active universe + symbol meta +
    news features so the evolution loop has something to evaluate.
    Synchronous: returns once the refresh completes (a few minutes).
    """
    await factor_pipeline.daily_data_refresh()
    return {"status": "ok", "message": "daily data refresh complete"}


@router.get("/admin/panel-columns")
async def admin_panel_columns() -> dict[str, Any]:
    """Diagnostic — what columns does get_panel actually expose, and how
    many non-null cells per fundamentals column?

    For pb_ratio/roe returning n_obs=0 vs eps_ttm/market_cap working.
    """
    from datetime import date as _date_cls

    from app.services import factor_data_service

    end = _date_cls.today()
    start = _date_cls(end.year - 4, end.month, min(end.day, 28))
    panel = await factor_data_service.get_panel(start, end)
    if panel.empty:
        return {"empty": True}
    cols_info = {}
    for col in panel.columns:
        cells = int(panel[col].notna().sum())
        cols_info[col] = {"non_null": cells, "total": int(panel.shape[0])}
    return {
        "shape": list(panel.shape),
        "columns": cols_info,
    }


@router.get("/admin/sample-fundamentals")
async def admin_sample_fundamentals(limit: int = 5) -> dict[str, Any]:
    """Dump a sample of factor_daily_fundamentals rows + null counts.

    Diagnostic for Phase 3.2 — confirms whether Polygon-derived fields
    are actually stored or all-None.
    """
    from sqlalchemy import func as _func

    from app.db.tables import FactorDailyFundamentals as _FF

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(_FF).order_by(desc(_FF.date)).limit(limit)
            )
        ).scalars().all()
        total = (await session.execute(_func.count(_FF.symbol).select())).scalar() or 0
        non_null_pb = (
            await session.execute(
                _func.count(_FF.pb_ratio).select()
            )
        ).scalar() or 0
        non_null_roe = (
            await session.execute(
                _func.count(_FF.roe).select()
            )
        ).scalar() or 0
        non_null_eps = (
            await session.execute(
                _func.count(_FF.eps_ttm).select()
            )
        ).scalar() or 0
        non_null_mc = (
            await session.execute(
                _func.count(_FF.market_cap).select()
            )
        ).scalar() or 0
    return {
        "total_rows": int(total),
        "non_null_market_cap": int(non_null_mc),
        "non_null_pb_ratio": int(non_null_pb),
        "non_null_roe": int(non_null_roe),
        "non_null_eps_ttm": int(non_null_eps),
        "samples": [
            {
                "symbol": r.symbol,
                "date": r.date.isoformat(),
                "market_cap": r.market_cap,
                "pe_ratio": r.pe_ratio,
                "pb_ratio": r.pb_ratio,
                "eps_ttm": r.eps_ttm,
                "revenue_ttm": r.revenue_ttm,
                "gross_margin": r.gross_margin,
                "debt_to_equity": r.debt_to_equity,
                "roe": r.roe,
            }
            for r in rows
        ],
    }


@router.post("/admin/refresh-fundamentals")
async def admin_refresh_fundamentals(top_n: int = 100) -> dict[str, Any]:
    """Refresh fundamentals from Polygon for the active universe.

    Sequential per-symbol I/O at ~2 RPS to respect rate limits, so
    100 symbols ≈ 1 minute. Returns the row count written.
    """
    from app.services import factor_fundamentals_service

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyActiveUniverse)
                .where(
                    DailyActiveUniverse.date == (
                        await session.execute(
                            select(DailyActiveUniverse.date)
                            .order_by(desc(DailyActiveUniverse.date))
                            .limit(1)
                        )
                    ).scalar()
                )
                .order_by(DailyActiveUniverse.rank)
                .limit(top_n)
            )
        ).scalars().all()
    symbols = [r.symbol for r in rows]
    if not symbols:
        return {"refreshed": 0, "message": "no active universe"}
    written = await factor_fundamentals_service.refresh_fundamentals(symbols)
    return {"refreshed": written, "symbols_attempted": len(symbols)}


@router.post("/admin/reset-population")
async def admin_reset_population() -> dict[str, Any]:
    """Wipe FactorPopulationState and reseed from WorldQuant Alpha 101.

    The current 50 slots are stale rows from broken pre-fix runs (every
    fitness=-99). The continuous loop normally evolves the population
    away from junk over time, but with each generation taking 10+ min on
    real data and most mutations producing sub-threshold fitness, that
    drift is too slow. Reset gives the GP search a fresh, known-tradable
    starting point.

    Each reseed slot stores the formula text with fitness=0.0 so the
    next generation evaluates them; the loop's next mutation/crossover
    pass then works from real Alpha 101 alphas instead of -99 noise.
    """
    from sqlalchemy import delete as _delete

    from core.factors.seeds import get_seed_population
    from core.factors.ast import serialize as _serialize

    seeds = list(get_seed_population())
    async with AsyncSessionLocal() as session:
        await session.execute(_delete(FactorPopulationState))
        for slot, node in enumerate(seeds[:50]):
            session.add(
                FactorPopulationState(
                    slot=slot,
                    formula=_serialize(node),
                    fitness=0.0,
                    generation=0,
                )
            )
        await session.commit()
    return {"deleted_old_slots": 50, "reseeded_slots": min(len(seeds), 50)}


@router.post("/admin/regenerate-recommendations")
async def admin_regenerate_recommendations(top_k: int = 10) -> dict[str, Any]:
    """Re-run today's recommendations against the current library.

    The daily refresh ran when the library was empty; this lets us
    rebuild today's picks without waiting for the next cron tick.
    """
    half = max(1, top_k // 2)
    rows = await today_recommendations_service.generate_today_recommendations(
        top_k_buy=half, top_k_sell=top_k - half
    )
    return {"generated": len(rows or []), "top_k": top_k}


@router.post("/admin/seed-library")
async def admin_seed_library(force: bool = False) -> dict[str, Any]:
    """Backtest the WorldQuant Alpha 101 seed set and insert passers.

    Bypasses the slow GP loop so the library has a baseline of known-
    good factors without waiting for evolution to discover them. Each
    seed runs through ``backtest_factor`` (4y panel) and the same
    ``add_factor`` gate the loop uses — so anything inserted here would
    have passed organically too.

    ``force=true`` first deletes existing alpha101_seed rows so a
    re-run on improved metrics (e.g. after enabling sector/market
    neutralization) can replace stale entries that ``is_duplicate``
    would otherwise shadow.
    """
    if force:
        from sqlalchemy import delete as _delete
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                _delete(FactorRecord).where(
                    FactorRecord.metadata_json.like('%"source": "alpha101_seed"%')
                )
            )
            await session.commit()
            logger.info("seed-library force purge: deleted %d rows", res.rowcount or 0)
    from datetime import date as _date_cls

    import numpy as _np

    from app.services import factor_backtest_service
    from core.factors.seeds import get_seed_population
    from core.factors.ast import serialize as _serialize

    seeds = list(get_seed_population())
    end = _date_cls.today()
    start = _date_cls(end.year - 4, end.month, min(end.day, 28))

    attempted = 0
    inserted = 0
    rejected = 0
    failed = 0
    insertions: list[dict[str, Any]] = []

    for node in seeds:
        attempted += 1
        formula = _serialize(node)
        try:
            r = await factor_backtest_service.backtest_factor(
                formula, start=start, end=end, universe_size=100,
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            insertions.append({"formula": formula[:80], "outcome": f"backtest_error: {str(exc)[:60]}"})
            continue

        return_curve = list(r.return_curve or [])
        return_emb = (
            factor_vector_store.embed_return_series(
                _np.asarray(return_curve, dtype=_np.float32)
            )
            if return_curve else None
        )
        row_id = await factor_vector_store.add_factor(
            formula,
            fitness=float(r.fitness) if r.fitness is not None else 0.0,
            ic_1d=r.ic_1d, ic_5d=r.ic_5d, ic_20d=r.ic_20d,
            icir=r.icir_5d, sharpe=r.sharpe,
            max_drawdown=r.max_drawdown, turnover=r.turnover,
            n_obs=r.n_obs, return_embedding=return_emb,
            generation=0,
            metadata={"source": "alpha101_seed"},
        )
        if row_id is None:
            rejected += 1
            insertions.append({
                "formula": formula[:80],
                "outcome": "rejected_by_gate",
                "fitness": r.fitness, "ic_5d": r.ic_5d,
                "sharpe": r.sharpe, "max_drawdown": r.max_drawdown,
            })
        else:
            inserted += 1
            insertions.append({
                "formula": formula[:80],
                "outcome": "inserted",
                "row_id": row_id,
                "fitness": r.fitness, "ic_5d": r.ic_5d,
                "sharpe": r.sharpe, "max_drawdown": r.max_drawdown,
            })

    if inserted:
        await factor_pipeline.bump_active_run_persisted(inserted)

    return {
        "attempted": attempted,
        "inserted": inserted,
        "rejected": rejected,
        "failed": failed,
        "details": insertions,
    }


@router.post("/admin/test-backtest")
async def admin_test_backtest(formula: str | None = None) -> dict[str, Any]:
    """Run one backtest in-process and return all metric fields.

    Diagnostic only — bypasses the GP loop and subprocess executor so we
    can see what the evaluator actually produces. ``formula`` defaults
    to a known-non-trivial Alpha 101 formula. Returns BacktestResult
    fields plus n_obs, n_days, panel size for triage.
    """
    from datetime import date as _date_cls

    from app.services import factor_backtest_service, factor_data_service

    test_formula = formula or "neg(correlation(rank(open),rank(volume),10))"
    end = _date_cls.today()
    start = _date_cls(end.year - 4, end.month, min(end.day, 28))

    panel_rows = 0
    panel_symbols = 0
    try:
        panel = await factor_data_service.get_panel(start, end)
        panel_rows = int(panel.shape[0])
        panel_symbols = (
            int(panel.index.get_level_values("symbol").nunique())
            if not panel.empty else 0
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "stage": "get_panel",
            "error": str(exc)[:200],
            "formula": test_formula,
        }

    try:
        result = await factor_backtest_service.backtest_factor(
            test_formula, start=start, end=end, universe_size=100,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "stage": "backtest_factor",
            "error": str(exc)[:200],
            "formula": test_formula,
            "panel_rows": panel_rows,
            "panel_symbols": panel_symbols,
        }

    return {
        "ok": True,
        "formula": test_formula,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "panel_rows": panel_rows,
        "panel_symbols": panel_symbols,
        "fitness": result.fitness,
        "ic_1d": result.ic_1d,
        "ic_5d": result.ic_5d,
        "ic_20d": result.ic_20d,
        "icir_5d": result.icir_5d,
        "rank_ic_5d": result.rank_ic_5d,
        "sharpe": result.sharpe,
        "sortino": result.sortino,
        "calmar": result.calmar,
        "max_drawdown": result.max_drawdown,
        "turnover": result.turnover,
        "win_rate": result.win_rate,
        "n_days": result.n_days,
        "n_obs": result.n_obs,
        "return_curve_len": len(result.return_curve or []),
    }


@router.get("/admin/data-status")
async def admin_data_status() -> dict[str, Any]:
    """Diagnostic snapshot of the underlying-data pipeline state.

    Returns counts and the most-recent date for the three tables that
    govern whether the evolution loop has anything to evaluate:
    ``factor_daily_bars``, ``factor_daily_active_universe``,
    ``factor_records``. Used to verify a refresh actually landed bars
    without grepping Railway logs.
    """
    from sqlalchemy import func as _func

    async with AsyncSessionLocal() as session:
        bars_count = (
            await session.execute(_func.count(DailyBar.symbol).select())
        ).scalar() or 0
        bars_max_date = (
            await session.execute(_func.max(DailyBar.date).select())
        ).scalar()
        bars_distinct_symbols = (
            await session.execute(
                _func.count(_func.distinct(DailyBar.symbol)).select()
            )
        ).scalar() or 0
        universe_count = (
            await session.execute(
                _func.count(DailyActiveUniverse.rank).select()
            )
        ).scalar() or 0
        universe_max_date = (
            await session.execute(
                _func.max(DailyActiveUniverse.date).select()
            )
        ).scalar()
        factors_count = (
            await session.execute(_func.count(FactorRecord.id).select())
        ).scalar() or 0
    return {
        "bars": {
            "row_count": int(bars_count),
            "distinct_symbols": int(bars_distinct_symbols),
            "most_recent_date": bars_max_date.isoformat() if bars_max_date else None,
        },
        "universe": {
            "row_count": int(universe_count),
            "most_recent_date": universe_max_date.isoformat() if universe_max_date else None,
        },
        "factor_records": {
            "row_count": int(factors_count),
        },
    }


@router.post("/admin/purge-bad-records")
async def admin_purge_bad_records() -> dict[str, int]:
    """Delete factor_records rows that slipped past the gate with bad
    metrics: ``fitness <= 0`` or any NaN core metric.

    Returns ``{"deleted": N}``. Idempotent.
    """
    from sqlalchemy import delete, or_

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(FactorRecord).where(
                or_(
                    FactorRecord.fitness <= 0.0,
                    FactorRecord.fitness.is_(None),
                    FactorRecord.ic_5d.is_(None),
                )
            )
        )
        await session.commit()
        deleted = int(result.rowcount or 0)
    return {"deleted": deleted}


_HISTORY_MAX_LIMIT = 1000
_HISTORY_DEFAULT_LIMIT = 100


@router.get("/evolution/history", response_model=GenerationHistoryResponse)
async def get_evolution_history(
    limit: int = _HISTORY_DEFAULT_LIMIT,
) -> GenerationHistoryResponse:
    """Per-generation summaries, oldest-first.

    The query selects the most recent ``limit`` rows by generation
    descending, then reverses so the response is in chronological order
    — matches what a line chart consumes directly.
    """
    capped = min(max(int(limit), 1), _HISTORY_MAX_LIMIT)
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorGenerationStat)
                .order_by(desc(FactorGenerationStat.generation))
                .limit(capped)
            )
        ).scalars().all()
    ordered = list(reversed(rows))
    items = [GenerationStatView.model_validate(r) for r in ordered]
    return GenerationHistoryResponse(items=items)


@router.get("/landscape", response_model=LandscapeResponse)
async def get_landscape(limit: int = 500) -> LandscapeResponse:
    """PCA-2D projection of factor formula embeddings, sorted by fitness."""
    capped = min(max(int(limit), 1), 2000)
    points = await factor_landscape_service.compute_landscape(limit=capped)
    return LandscapeResponse(items=[LandscapePoint(**p) for p in points])


@router.get("/recommendations/today", response_model=RecommendationsResponse)
async def get_today_recommendations(top_k: int = 10) -> RecommendationsResponse:
    """Return today's persisted recommendations.

    Generates them on the first hit of the day if the table is empty so
    the UI never sees a stale-but-loadable empty state when the cron
    hasn't fired yet (e.g. dev server boot).
    """
    items = await today_recommendations_service.get_today_recommendations()
    if not items:
        half = max(1, top_k // 2)
        await today_recommendations_service.generate_today_recommendations(
            top_k_buy=half, top_k_sell=top_k - half
        )
        items = await today_recommendations_service.get_today_recommendations()
    return RecommendationsResponse(
        items=[RecommendationView.model_validate(it) for it in items[:top_k]],
        generated_at=items[0]["date"] if items else None,
    )


@router.get("/trajectories", response_model=TrajectoriesResponse)
async def list_trajectories(limit: int = 200) -> TrajectoriesResponse:
    """Recent QuantaAlpha trajectories — drives the evolution lineage tree."""
    capped = min(max(int(limit), 1), 1000)
    items = await factor_quanta_service.list_trajectories(limit=capped)
    return TrajectoriesResponse(
        items=[TrajectoryNodeView.model_validate(it) for it in items]
    )


@router.get("/evolution/population", response_model=PopulationSnapshotResponse)
async def get_evolution_population() -> PopulationSnapshotResponse:
    """Current GP population: one entry per slot with its formula + fitness."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorPopulationState).order_by(FactorPopulationState.slot)
            )
        ).scalars().all()
    if not rows:
        return PopulationSnapshotResponse(generation=0, slots=[])
    gen = max(int(r.generation) for r in rows)
    slots = [
        PopulationSlotView(
            slot=int(r.slot),
            formula=str(r.formula),
            fitness=float(r.fitness),
        )
        for r in rows
    ]
    return PopulationSnapshotResponse(generation=gen, slots=slots)


@router.post("/qa", response_model=QAResponse)
async def factor_qa(body: QARequest) -> QAResponse:
    """Natural-language Q&A using OpenAI tool-calling over our pre-defined tools.

    SECURITY: the LLM never writes/executes Python — it only picks from a
    whitelisted tool registry. Question is also keyword-screened.
    """
    if not body.question or not body.question.strip():
        raise HTTPException(status_code=400, detail="question is empty")
    result = await factor_qa_service.answer_question(body.question.strip())
    return QAResponse(
        answer=result["answer"],
        tool_calls=[QAToolCall(**tc) for tc in result.get("tool_calls", [])],
        blocked=bool(result.get("blocked", False)),
    )
