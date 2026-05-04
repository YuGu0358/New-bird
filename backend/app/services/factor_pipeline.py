"""Factor Forge orchestration — continuous evolution loop + daily data refresh.

Two coroutines run side-by-side:

1. ``daily_data_refresh()``  — registered on APScheduler at 21:35 UTC.
   Pulls fresh OHLCV, recomputes the active universe, fetches news, and
   retrains the LightGBM predictor.

2. ``continuous_evolution_loop()`` — long-running background task started
   on app boot. One generation per cycle, 60s sleep between cycles, runs
   forever until :func:`stop_loop` is called. State persists in
   ``FactorPopulationState`` and ``FactorEvolutionStateSingleton`` so a
   restart resumes from the last generation.

The heavy GP/backtest math runs in a ``ProcessPoolExecutor`` subprocess
so it cannot hold the main event loop's GIL. Persistence (which calls
OpenAI for embeddings) is done back on the main process where async I/O
behaves correctly.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
import statistics
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
from sqlalchemy import delete, select

from app.db.engine import AsyncSessionLocal
from app.db.tables import (
    FactorEvolutionStateSingleton,
    FactorGenerationStat,
    FactorPopulationState,
)
from app.services import (
    factor_data_service,
    factor_fitness_predictor,
    factor_gp_service,
    factor_meta_service,
    factor_news_service,
    factor_vector_store,
)

try:  # FF-E may not be wired yet — degrade gracefully if its imports fail.
    from app.services import factor_llm_mutation_service as llm_mut
except Exception:  # pragma: no cover - defensive
    llm_mut = None  # type: ignore[assignment]

from core.factors.ast import FactorNode, parse, serialize
from core.factors.genetic import mutate
from core.factors.op_stats import compute_op_weights
from core.factors.seeds import get_seed_population

logger = logging.getLogger(__name__)


# ----- Constants -------------------------------------------------------------

_TARGET_POP = 50
_GENERATION_SLEEP_SEC = 60.0
_PREDICTOR_MIN_RECORDS = 30
_ERROR_TRUNCATE = 500
_DAILY_JOB_ID = "factor_forge_daily_refresh"
_DAILY_HOUR_UTC = 21
_DAILY_MINUTE_UTC = 35
_PREDICTOR_RETRAIN_EVERY = 5
_LLM_INJECT_EVERY = 5
_LLM_VARIANT_COUNT = 5
_QUANTA_FRACTION_HYBRID = 0.5  # in hybrid mode, this share of the pop is QuantaAlpha-driven
_QUANTA_VARIANTS_PER_GEN = 5  # how many trajectories injected per generation
_COLLAPSE_TOLERANCE = 1e-3
_COLLAPSE_TOP_N = 5
_NEWS_TOP_N = 100


# ----- Module-level state ----------------------------------------------------

_loop_task: Optional[asyncio.Task] = None
_loop_lock = asyncio.Lock()
_should_stop = asyncio.Event()


# ----- Helpers ---------------------------------------------------------------


def _evolution_mode() -> str:
    """`gp` (legacy AST GP) / `quanta` (LLM trajectory) / `hybrid`. Default hybrid."""
    from app import runtime_settings

    raw = (
        runtime_settings.get_setting("FACTOR_EVOLUTION_MODE", "hybrid") or "hybrid"
    ).strip().lower()
    return raw if raw in {"gp", "quanta", "hybrid"} else "hybrid"


def _seeded_population(rng: random.Random, target: int) -> list[FactorNode]:
    """Initial pop = seeds + seed mutations only (NO fully random trees)."""
    seeds = list(get_seed_population())
    if not seeds:
        return []
    pop: list[FactorNode] = []
    # 60% verbatim seed copies (cycling), remainder with one mutation each.
    seed_copies = int(target * 0.6)
    while len(pop) < seed_copies:
        pop.append(seeds[len(pop) % len(seeds)])
    while len(pop) < target:
        base = seeds[rng.randrange(len(seeds))]
        pop.append(mutate(base, rng, mutation_rate=1.0))
    return pop[:target]


async def _load_singleton() -> FactorEvolutionStateSingleton:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FactorEvolutionStateSingleton).where(
                    FactorEvolutionStateSingleton.id == 1
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = FactorEvolutionStateSingleton(id=1)
            session.add(row)
            await session.commit()
            await session.refresh(row)
    return row


async def _save_singleton(**kwargs) -> None:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FactorEvolutionStateSingleton).where(
                    FactorEvolutionStateSingleton.id == 1
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = FactorEvolutionStateSingleton(id=1)
            session.add(row)
        for key, value in kwargs.items():
            setattr(row, key, value)
        await session.commit()


async def _load_population() -> list[FactorNode]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorPopulationState).order_by(FactorPopulationState.slot)
            )
        ).scalars().all()
    out: list[FactorNode] = []
    for r in rows:
        try:
            out.append(parse(r.formula))
        except Exception:
            logger.debug("dropping unparseable persisted slot: %r", r.formula[:80])
            continue
    return out


async def _save_population(
    pop: list[FactorNode],
    fitnesses: list[float],
    generation: int,
) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(FactorPopulationState))
        now = datetime.now(timezone.utc)
        for slot, cand in enumerate(pop):
            fit = fitnesses[slot] if slot < len(fitnesses) else None
            session.add(
                FactorPopulationState(
                    slot=slot,
                    formula=serialize(cand),
                    fitness=float(fit) if fit is not None else -99.0,
                    generation=int(generation),
                    updated_at=now,
                )
            )
        await session.commit()


async def _save_generation_stat(
    *,
    generation: int,
    fitnesses: list[float],
    best: float | None,
    persisted_count: int,
) -> None:
    """Append a ``FactorGenerationStat`` row summarising one generation.

    Median is computed across "evaluated" fitnesses only — pre-filtered
    rows carry the sentinel ``-99.0`` and would skew the median if
    included.
    """
    finite = [f for f in fitnesses if f > -50.0]
    median_fit = float(statistics.median(finite)) if finite else None
    async with AsyncSessionLocal() as session:
        session.add(
            FactorGenerationStat(
                generation=int(generation),
                best_fitness=float(best) if best is not None else None,
                median_fitness=median_fit,
                persisted_count=int(persisted_count),
                evaluated_count=len(fitnesses),
                completed_at=datetime.now(timezone.utc),
            )
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.warning(
                "failed to persist FactorGenerationStat for gen=%d",
                generation, exc_info=True,
            )


def _detect_collapse(fitnesses: list[float]) -> bool:
    """Top-5 fitness all within 1e-3 of each other → population collapsed."""
    sorted_fit = sorted([f for f in fitnesses if f > -50.0], reverse=True)[:_COLLAPSE_TOP_N]
    if len(sorted_fit) < _COLLAPSE_TOP_N:
        return False
    return (max(sorted_fit) - min(sorted_fit)) < _COLLAPSE_TOLERANCE


# ----- One generation --------------------------------------------------------


def _run_generation_blocking(
    pop: list[FactorNode],
    *,
    start: date,
    end: date,
    rng: random.Random,
    pre_filter,
    generation: int,
    op_weights: dict[str, float] | None = None,
) -> tuple[list[FactorNode], list[float], object, list]:
    """DEPRECATED — kept for backward compatibility only.

    The continuous evolution loop now runs the GP work in a
    ``ProcessPoolExecutor`` via :func:`_run_generation_subprocess`. This
    in-thread variant is no longer called; it exists so any external
    caller still importing it gets a clear (still working) path that
    blocks the calling thread.
    """
    return asyncio.run(
        factor_gp_service.run_generation(
            pop,
            start=start,
            end=end,
            rng=rng,
            universe_size=100,
            elite_frac=0.3,
            tournament_k=4,
            crossover_rate=0.6,
            mutation_rate=0.3,
            pre_score_filter=pre_filter,
            fitness_threshold=0.02,
            persist=True,
            generation=generation,
            op_weights=op_weights,
        )
    )


# ----- Subprocess plumbing ---------------------------------------------------


_executor: Optional[ProcessPoolExecutor] = None


def _get_executor() -> ProcessPoolExecutor:
    """Lazy-init the shared 1-worker process pool.

    Reused across generations so we pay the import + warm-up cost only
    once. ``max_workers=1`` is intentional — this isolates the GP
    backtest from the API event loop, it is not a parallelisation knob.
    """
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=1)
    return _executor


def _shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        try:
            _executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        _executor = None


def _resolve_db_url() -> str:
    """The same SQLite URL the main process uses, so the subprocess
    reads from / writes to the same DB file."""
    import app.db.engine as engine_module  # see _run_generation_subprocess for why

    return str(engine_module.engine.url)


def _run_generation_subprocess(
    formula_strings: list[str],
    *,
    start_iso: str,
    end_iso: str,
    universe_size: int,
    elite_frac: float,
    tournament_k: int,
    crossover_rate: float,
    mutation_rate: float,
    fitness_threshold: float,
    generation: int,
    op_weights: dict[str, float] | None,
    rng_seed: int,
    db_url: str,
) -> dict:
    """Run one GP generation entirely inside a subprocess.

    Top-level (pickleable) so ``ProcessPoolExecutor`` can dispatch it.

    Returns a JSON-pickleable dict:
      {
        "results": [
          { "formula": str, "fitness": float, "ic_1d": float|None,
            "ic_5d": float|None, "ic_20d": float|None, "icir_5d": float|None,
            "sharpe": float|None, "max_drawdown": float|None,
            "turnover": float|None, "n_obs": int|None,
            "return_curve": list[float] }
          ...
        ],
        "next_pop_formulas": [str, ...],
        "stats": { "best_fitness": ..., "median_fitness": ... },
      }

    Persistence to ``factor_records`` (which embeds via OpenAI) is left
    to the parent process — this subprocess only computes.
    """
    import asyncio as _asyncio
    import random as _random

    from datetime import date as _date

    from sqlalchemy.ext.asyncio import (
        async_sessionmaker as _async_sessionmaker,
        create_async_engine as _create_async_engine,
    )

    # NB: ``app.db.__init__.py`` re-exports the AsyncEngine instance as
    # ``engine``, which shadows the submodule of the same name. ``from
    # app.db import engine as X`` therefore binds X to the AsyncEngine
    # instance — assignment to ``X.engine`` then hits AsyncEngine's
    # ``engine`` property which has no setter (= 500). Use an explicit
    # ``import app.db.engine`` to bind the SUBMODULE.
    import sys  # noqa: PLC0415
    import app.db.engine  # noqa: F401, PLC0415 — force submodule load
    engine_module = sys.modules["app.db.engine"]  # bypass __init__.py shadowing

    # Open a fresh engine bound to the same SQLite file. Patch the
    # module-level AsyncSessionLocal so factor_data_service /
    # factor_meta_service / factor_news_service (which bound the symbol
    # at import time) read from it.
    new_engine = _create_async_engine(db_url, future=True)
    new_factory = _async_sessionmaker(new_engine, expire_on_commit=False)
    engine_module.engine = new_engine
    engine_module.AsyncSessionLocal = new_factory

    from app.services import (
        factor_data_service as _fds,
        factor_meta_service as _fms,
        factor_news_service as _fns,
    )

    _fds.AsyncSessionLocal = new_factory
    _fms.AsyncSessionLocal = new_factory
    _fns.AsyncSessionLocal = new_factory
    # Note: NOT patching factor_vector_store — we won't call add_factor
    # in this subprocess, so its session reference does not matter.

    from app.services import factor_gp_service as _gp
    from core.factors.ast import parse as _parse, serialize as _serialize

    pop: list = []
    for formula_str in formula_strings:
        try:
            pop.append(_parse(formula_str))
        except Exception:
            continue
    if not pop:
        return {"results": [], "next_pop_formulas": [], "stats": {}}

    rng = _random.Random(rng_seed)

    async def _go() -> dict:
        try:
            next_pop, fitnesses, stats, backtest_results = await _gp.run_generation(
                pop,
                start=_date.fromisoformat(start_iso),
                end=_date.fromisoformat(end_iso),
                rng=rng,
                universe_size=universe_size,
                elite_frac=elite_frac,
                tournament_k=tournament_k,
                crossover_rate=crossover_rate,
                mutation_rate=mutation_rate,
                # Pre-filter is applied on the main process before this
                # subprocess is invoked; passing None here avoids loading
                # the LightGBM predictor inside the subprocess.
                pre_score_filter=None,
                fitness_threshold=fitness_threshold,
                # IMPORTANT: parent process owns persistence (OpenAI
                # embeddings need async I/O on the main loop).
                persist=False,
                generation=generation,
                op_weights=op_weights,
            )
        except Exception:
            # If the whole generation blew up (e.g. missing API key),
            # surface zero results back to the parent so the loop just
            # records the failure and tries again next cycle.
            return {"results": [], "next_pop_formulas": [], "stats": {}}

        results: list[dict] = []
        for cand, fit, r in zip(pop, fitnesses, backtest_results):
            entry: dict = {
                "formula": _serialize(cand),
                "fitness": float(fit),
            }
            if r is not None:
                entry.update(
                    {
                        "ic_1d": _safe_float(getattr(r, "ic_1d", None)),
                        "ic_5d": _safe_float(getattr(r, "ic_5d", None)),
                        "ic_20d": _safe_float(getattr(r, "ic_20d", None)),
                        "icir_5d": _safe_float(getattr(r, "icir_5d", None)),
                        "sharpe": _safe_float(getattr(r, "sharpe", None)),
                        "max_drawdown": _safe_float(
                            getattr(r, "max_drawdown", None)
                        ),
                        "turnover": _safe_float(getattr(r, "turnover", None)),
                        "n_obs": int(getattr(r, "n_obs", 0) or 0),
                        "return_curve": list(getattr(r, "return_curve", []) or []),
                    }
                )
            results.append(entry)

        return {
            "results": results,
            "next_pop_formulas": [_serialize(c) for c in next_pop],
            "stats": {
                "best_fitness": (
                    float(stats.best_fitness) if stats is not None else None
                ),
                "median_fitness": (
                    float(stats.median_fitness) if stats is not None else None
                ),
            },
        }

    try:
        return _asyncio.run(_go())
    finally:
        try:
            _asyncio.run(new_engine.dispose())
        except Exception:
            pass


def _safe_float(v) -> float | None:  # noqa: ANN001
    """Round-trip floats through json — coerce NaN/Inf/None to None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # NaN / +/-inf survive float() but fail json/pickle round trips
    # cleanly downstream; collapse them to None here.
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


# ----- One generation (main-process orchestration) --------------------------


_PRE_FILTER_MIN_SURVIVORS = 4


async def _run_one_generation(
    pop: list[FactorNode],
    *,
    rng: random.Random,
    generation: int,
    end: date | None = None,
) -> tuple[list[FactorNode], list[float], float | None, int]:
    """Score the population and produce the next generation.

    Returns ``(next_pop, fitnesses_just_evaluated, best_fitness, new_persisted)``.

    Architecture:
      * The cheap LightGBM pre-filter runs on the **main** process —
        cheap CPU, model is already loaded here, and we'd rather not
        ship the trained model into the subprocess on every generation.
      * The heavy backtest/GP math runs in a **subprocess** via
        ``ProcessPoolExecutor(max_workers=1)`` so the API event loop is
        not subject to GIL contention from numpy/pandas.
      * Persistence (``factor_vector_store.add_factor`` → OpenAI
        embedding API) runs back on the main process, so async I/O
        stays where it belongs.
    """
    end = end or date.today()
    start = date(end.year - 2, end.month, min(end.day, 28))

    # Predictor pre-filter on MAIN process (no GIL contention with
    # subprocess; saves the cost of shipping the LightGBM model across
    # the process boundary every generation).
    pop_for_subprocess = pop
    predictor = factor_fitness_predictor.load_predictor()
    if predictor.is_trained and pop:
        try:
            predicted = [predictor.predict(c) for c in pop]
            threshold = float(np.median(predicted)) if predicted else float("-inf")
            survivors = [c for c, p in zip(pop, predicted) if p >= threshold]
            if len(survivors) >= _PRE_FILTER_MIN_SURVIVORS:
                pop_for_subprocess = survivors
        except Exception:
            logger.debug("pre-filter failed; skipping", exc_info=True)

    # Operator-success weights — bias mutation toward ops appearing in
    # high-fitness library factors. Falls back to uniform when library is
    # empty or fetch fails.
    op_weights: dict[str, float] | None = None
    try:
        records = await factor_vector_store.list_factors(limit=2000)
        op_weights = compute_op_weights(records) if records else None
    except Exception:
        logger.debug("op_weights fetch failed; falling back to uniform", exc_info=True)
        op_weights = None

    formula_strings = [serialize(c) for c in pop_for_subprocess]
    rng_seed = rng.randrange(2**31)
    db_url = _resolve_db_url()

    loop = asyncio.get_running_loop()
    payload = await loop.run_in_executor(
        _get_executor(),
        functools.partial(
            _run_generation_subprocess,
            formula_strings,
            start_iso=start.isoformat(),
            end_iso=end.isoformat(),
            universe_size=100,
            elite_frac=0.3,
            tournament_k=4,
            crossover_rate=0.6,
            mutation_rate=0.3,
            fitness_threshold=0.02,
            generation=generation,
            op_weights=op_weights,
            rng_seed=rng_seed,
            db_url=db_url,
        ),
    )

    results = payload.get("results", [])
    fitnesses: list[float] = [float(r.get("fitness", -99.0)) for r in results]

    # Persist passing factors back on the main process. ``add_factor``
    # calls OpenAI for embeddings — async I/O, won't block other tasks.
    new_persisted = 0
    for r in results:
        fit = r.get("fitness")
        if fit is None or fit < 0.02:
            continue
        try:
            return_curve = r.get("return_curve") or []
            return_emb = (
                factor_vector_store.embed_return_series(
                    np.asarray(return_curve, dtype=np.float32)
                )
                if return_curve
                else None
            )
            row_id = await factor_vector_store.add_factor(
                r["formula"],
                fitness=fit,
                ic_1d=r.get("ic_1d"),
                ic_5d=r.get("ic_5d"),
                ic_20d=r.get("ic_20d"),
                icir=r.get("icir_5d"),
                sharpe=r.get("sharpe"),
                max_drawdown=r.get("max_drawdown"),
                turnover=r.get("turnover"),
                n_obs=r.get("n_obs"),
                return_embedding=return_emb,
                generation=generation,
            )
            if row_id is not None:
                new_persisted += 1
        except Exception:
            logger.debug(
                "add_factor failed for %s", r.get("formula", "")[:60], exc_info=True
            )

    next_pop: list[FactorNode] = []
    for s in payload.get("next_pop_formulas", []):
        try:
            next_pop.append(parse(s))
        except Exception:
            continue

    # Collapse-detection: if the elite all converge, inject seed mutations.
    if _detect_collapse(fitnesses):
        seeds = list(get_seed_population())
        if seeds:
            injected: list[FactorNode] = []
            for _ in range(5):
                base = seeds[rng.randrange(len(seeds))]
                injected.append(mutate(base, rng, mutation_rate=1.0))
            next_pop = (next_pop[: _TARGET_POP - len(injected)]) + injected
            logger.info(
                "[FF gen=%d] population collapse detected, injected %d seed-mutations",
                generation, len(injected),
            )

    # LLM intelligent mutation: every 5 generations, ask GPT for variants.
    if llm_mut is not None and (generation % _LLM_INJECT_EVERY == _LLM_INJECT_EVERY - 1):
        try:
            top = await factor_vector_store.list_factors(limit=10, sort_by="fitness")
            variants = await llm_mut.generate_variants(top, n_variants=_LLM_VARIANT_COUNT)
            if variants:
                keep = max(0, len(next_pop) - len(variants))
                next_pop = next_pop[:keep] + list(variants)
                logger.info(
                    "[FF gen=%d] LLM injected %d variants", generation, len(variants),
                )
        except Exception:
            logger.warning("LLM variant injection failed", exc_info=True)

    finite = [f for f in fitnesses if f > -50.0]
    best = max(finite) if finite else None
    return next_pop, fitnesses, best, new_persisted


# ----- The loop --------------------------------------------------------------


async def continuous_evolution_loop() -> None:
    """Run forever, one generation per cycle, until ``_should_stop`` is set."""
    logger.info("[FactorForge] continuous evolution loop starting")
    rng = random.Random()  # un-seeded — different every restart

    # One-shot audit at boot — re-screen the existing library against the
    # CLEAN heuristics so old records (e.g. neg(close), sharpe=4.7 outliers)
    # get quarantined automatically without manual SQL.
    try:
        from app.services import factor_audit_service
        audit_result = await factor_audit_service.audit_library()
        if audit_result["newly_quarantined"]:
            logger.info(
                "[FactorForge] startup audit: %d newly quarantined out of %d scanned",
                audit_result["newly_quarantined"],
                audit_result["scanned"],
            )
    except Exception:
        logger.warning("startup factor audit failed", exc_info=True)

    while not _should_stop.is_set():
        generation: int | None = None
        try:
            singleton = await _load_singleton()
            generation = int(singleton.current_generation) + 1

            # Load or seed population.
            pop = await _load_population()
            if not pop:
                pop = _seeded_population(rng, _TARGET_POP)
                logger.info(
                    "[FactorForge] seeded fresh population (%d)", len(pop),
                )

            # Run one generation. This wraps the heavy numpy work in a thread.
            (
                next_pop,
                fitnesses,
                best,
                persisted_count,
            ) = await _run_one_generation(
                pop, rng=rng, generation=generation,
            )

            # Persist new state.
            await _save_population(next_pop, fitnesses, generation)
            await _save_generation_stat(
                generation=generation,
                fitnesses=list(fitnesses),
                best=best,
                persisted_count=persisted_count,
            )
            await _save_singleton(
                current_generation=generation,
                best_fitness_recent=float(best) if best is not None else None,
                last_generation_completed_at=datetime.now(timezone.utc),
                last_error=None,
            )
            logger.info("[FactorForge] gen=%d done best=%s", generation, best)

            # QuantaAlpha trajectory injection (hybrid / quanta modes).
            mode = _evolution_mode()
            if mode in {"quanta", "hybrid"}:
                try:
                    from app.services import factor_quanta_service as quanta

                    recent_pool = [serialize(c) for c in next_pop[:8]]
                    library_records = await factor_vector_store.list_factors(
                        limit=20, sort_by="fitness"
                    )
                    injected = 0
                    n_to_inject = _QUANTA_VARIANTS_PER_GEN
                    n_generate = n_to_inject // 2
                    n_evolve = n_to_inject - n_generate
                    for _ in range(n_generate):
                        draft = await quanta.generate_trajectory(
                            recent_pool=recent_pool
                        )
                        if draft is None:
                            continue
                        await quanta.persist_trajectory(draft)
                        injected += 1
                    if library_records and n_evolve > 0:
                        parents = quanta.pick_parents_for_quanta(
                            library_records, n_evolve, rng
                        )
                        for parent in parents:
                            draft = await quanta.evolve_trajectory(
                                parent,
                                failure_reason=(
                                    "(no specific failure — periodic refinement)"
                                ),
                                recent_pool=recent_pool,
                            )
                            if draft is None:
                                continue
                            await quanta.persist_trajectory(draft)
                            injected += 1
                    if injected:
                        logger.info(
                            "[FactorForge gen=%d] quanta injected %d trajectories",
                            generation,
                            injected,
                        )
                except Exception:
                    logger.warning(
                        "quanta injection failed at gen=%d",
                        generation,
                        exc_info=True,
                    )

            # Retrain predictor every N generations.
            if generation % _PREDICTOR_RETRAIN_EVERY == 0:
                try:
                    await factor_fitness_predictor.train_from_library(
                        min_records=_PREDICTOR_MIN_RECORDS
                    )
                    logger.info(
                        "[FactorForge] predictor retrained at gen=%d", generation,
                    )
                except Exception:
                    logger.warning("predictor retrain failed", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — top of background loop
            logger.exception(
                "[FactorForge] generation %s crashed",
                generation if generation is not None else "?",
            )
            try:
                await _save_singleton(last_error=str(exc)[:_ERROR_TRUNCATE])
            except Exception:
                logger.warning("failed to persist last_error", exc_info=True)

        # Pause between cycles. Cancellable.
        try:
            await asyncio.wait_for(
                _should_stop.wait(), timeout=_GENERATION_SLEEP_SEC
            )
        except asyncio.TimeoutError:
            pass

    logger.info("[FactorForge] continuous loop exited")


# ----- Public control --------------------------------------------------------


async def start_loop() -> str:
    global _loop_task
    async with _loop_lock:
        if _loop_task is not None and not _loop_task.done():
            return "already running"
        _should_stop.clear()
        _loop_task = asyncio.create_task(
            continuous_evolution_loop(), name="factor_forge_loop"
        )
        return "started"


async def stop_loop(timeout: float = 5.0) -> str:
    global _loop_task
    async with _loop_lock:
        if _loop_task is None or _loop_task.done():
            _loop_task = None
            _shutdown_executor()
            return "not running"
        _should_stop.set()
        try:
            await asyncio.wait_for(_loop_task, timeout=timeout)
        except asyncio.TimeoutError:
            _loop_task.cancel()
            try:
                await _loop_task
            except (asyncio.CancelledError, Exception):
                pass
        finally:
            _loop_task = None
            _shutdown_executor()
        return "stopped"


def is_loop_running() -> bool:
    return _loop_task is not None and not _loop_task.done()


# ----- Daily data refresh (cron) --------------------------------------------


async def daily_data_refresh() -> None:
    """Refresh data + retrain predictor. NO evolution here — the loop runs that."""
    today = date.today()
    try:
        await factor_data_service.update_daily_bars()
        await factor_data_service.update_active_universe(today)
        symbols = await factor_data_service.get_active_universe(today, top_n=_NEWS_TOP_N)
        await factor_meta_service.refresh_symbol_meta(symbols)
        await factor_news_service.update_news_features(symbols, today)
        await factor_fitness_predictor.train_from_library(
            min_records=_PREDICTOR_MIN_RECORDS
        )
        # Generate today's recommendations once data + universe are fresh.
        try:
            from app.services import today_recommendations_service as recs

            await recs.generate_today_recommendations()
            logger.info("[FactorForge] today's recommendations generated")
        except Exception:
            logger.warning(
                "today_recommendations generation failed", exc_info=True
            )
        logger.info("[FactorForge] daily data refresh complete (%s)", today)
    except Exception:
        logger.exception("[FactorForge] daily data refresh failed")


async def schedule_default_jobs() -> None:
    """Register the daily refresh + auto-start the continuous loop.

    Idempotent and tolerant of a missing scheduler.
    """
    from app import scheduler as app_scheduler

    sched = app_scheduler.get_scheduler()
    if sched is not None:
        sched.add_job(
            daily_data_refresh,
            trigger="cron",
            id=_DAILY_JOB_ID,
            hour=_DAILY_HOUR_UTC,
            minute=_DAILY_MINUTE_UTC,
            replace_existing=True,
        )
        logger.info(
            "[FactorForge] daily refresh job registered (%02d:%02d UTC)",
            _DAILY_HOUR_UTC, _DAILY_MINUTE_UTC,
        )
    else:
        logger.info("[FactorForge] scheduler not running; skipping daily refresh job")

    # Always start the loop on boot. User can stop it via API if they want.
    await start_loop()


# ----- Status query ---------------------------------------------------------


async def evolution_status() -> dict:
    s = await _load_singleton()
    pop = await _load_population()
    library = await factor_vector_store.list_factors(limit=10_000)
    return {
        "is_running": is_loop_running(),
        "current_generation": int(s.current_generation),
        "best_fitness_recent": (
            float(s.best_fitness_recent)
            if s.best_fitness_recent is not None
            else None
        ),
        "last_generation_completed_at": s.last_generation_completed_at,
        "population_size": len(pop),
        "library_count": len(library),
        "error": s.last_error,
    }


# ----- Legacy compat --------------------------------------------------------


async def run_full_pipeline(*, target_date: date | None = None) -> int:  # noqa: ARG001
    """Removed. The continuous loop replaces this entry point.

    Kept only to surface a clear error if any caller still references it.
    """
    raise NotImplementedError(
        "run_full_pipeline has been removed; the continuous evolution loop "
        "now drives Factor Forge. Use start_loop()/stop_loop() instead."
    )


__all__ = [
    "continuous_evolution_loop",
    "daily_data_refresh",
    "evolution_status",
    "is_loop_running",
    "schedule_default_jobs",
    "start_loop",
    "stop_loop",
]
