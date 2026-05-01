"""Two-stage genetic-programming search for Factor Forge.

Wires the seed population (``core.factors.seeds``), pure genetic operators
(``core.factors.genetic``), the backtest engine
(``app.services.factor_backtest_service``), and the persistent factor
library (``app.services.factor_vector_store``) into a generational loop.

Public entry points:
  * :func:`run_generation` — score one population, persist survivors above
    threshold, return the next generation.
  * :func:`run_two_stage_evolution` — short-window stage 1 + long-window
    stage 2, returning aggregate stats and survivor formulas.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional, Sequence

import numpy as np

from core.factors.ast import FactorNode, serialize
from core.factors.genetic import (
    crossover,
    mutate,
    random_tree,
    tournament_select,
)
from core.factors.seeds import get_seed_population

from app.services import factor_backtest_service, factor_vector_store

logger = logging.getLogger(__name__)


# Sentinel fitness for skipped / failed candidates — below any IC threshold.
_SKIPPED_FITNESS: float = -99.0
_DAYS_PER_YEAR: float = 365.25


@dataclass(frozen=True)
class GenerationStats:
    generation: int
    population_size: int
    best_fitness: float
    median_fitness: float
    new_persisted: int
    elapsed_sec: float


@dataclass(frozen=True)
class EvolutionResult:
    stage_1_stats: list[GenerationStats]
    stage_2_stats: list[GenerationStats]
    survivors: list[str]


def _sample_panel_window(end: date, years: int) -> tuple[date, date]:
    return (end - timedelta(days=int(years * _DAYS_PER_YEAR)), end)


# ---------------------------------------------------------------------------
# Per-generation scoring + breeding
# ---------------------------------------------------------------------------


async def _score_population(
    population: Sequence[FactorNode],
    *,
    start: date,
    end: date,
    universe_size: int,
    pre_score_filter: Optional[Callable[[FactorNode], float]],
) -> tuple[list[float], list]:
    """Score every candidate via the backtest engine, with an optional
    cheap pre-filter to skip the worst half before paying for backtest."""
    if pre_score_filter is not None:
        predicted = [pre_score_filter(c) for c in population]
        threshold = float(np.median(predicted)) if predicted else float("-inf")
    else:
        predicted = [None] * len(population)
        threshold = float("-inf")

    fitnesses: list[float] = []
    results: list = []
    for cand, pred in zip(population, predicted):
        if pred is not None and pred < threshold:
            fitnesses.append(_SKIPPED_FITNESS)
            results.append(None)
            continue
        try:
            r = await factor_backtest_service.backtest_factor(
                cand, start=start, end=end, universe_size=universe_size,
            )
            fit = float(r.fitness) if np.isfinite(r.fitness) else _SKIPPED_FITNESS
            fitnesses.append(fit)
            results.append(r)
        except Exception:
            logger.warning(
                "backtest failed for %s", serialize(cand)[:80], exc_info=True
            )
            fitnesses.append(_SKIPPED_FITNESS)
            results.append(None)
    return fitnesses, results


async def _persist_survivors(
    population: Sequence[FactorNode],
    fitnesses: Sequence[float],
    backtest_results: Sequence,
    *,
    fitness_threshold: float,
    generation: int,
) -> int:
    new_persisted = 0
    for cand, fit, r in zip(population, fitnesses, backtest_results):
        if r is None or fit < fitness_threshold:
            continue
        ret_emb = factor_vector_store.embed_return_series(
            np.asarray(r.return_curve, dtype=np.float32)
        )
        row_id = await factor_vector_store.add_factor(
            serialize(cand),
            fitness=fit,
            ic_1d=r.ic_1d,
            ic_5d=r.ic_5d,
            ic_20d=r.ic_20d,
            icir=r.icir_5d,
            sharpe=r.sharpe,
            max_drawdown=r.max_drawdown,
            turnover=r.turnover,
            return_embedding=ret_emb,
            generation=generation,
            dedupe=True,
        )
        if row_id is not None:
            new_persisted += 1
    return new_persisted


def _breed_next_generation(
    population: Sequence[FactorNode],
    fitnesses: Sequence[float],
    *,
    rng: random.Random,
    elite_frac: float,
    tournament_k: int,
    crossover_rate: float,
    mutation_rate: float,
) -> list[FactorNode]:
    n = len(population)
    elite_count = max(1, int(n * elite_frac))
    sorted_idx = sorted(range(n), key=lambda i: fitnesses[i], reverse=True)
    elite = [population[i] for i in sorted_idx[:elite_count]]

    next_pop = list(elite)
    while len(next_pop) < n:
        if rng.random() < crossover_rate and len(elite) > 1:
            p1 = tournament_select(population, fitnesses, tournament_k, rng)
            p2 = tournament_select(population, fitnesses, tournament_k, rng)
            child = crossover(p1, p2, rng)
        else:
            child = tournament_select(population, fitnesses, tournament_k, rng)
        child = mutate(child, rng, mutation_rate=mutation_rate)
        next_pop.append(child)
    return next_pop


async def run_generation(
    population: list[FactorNode],
    *,
    start: date,
    end: date,
    rng: random.Random,
    universe_size: int = 100,
    elite_frac: float = 0.2,
    tournament_k: int = 4,
    crossover_rate: float = 0.6,
    mutation_rate: float = 0.3,
    pre_score_filter: Optional[Callable[[FactorNode], float]] = None,
    fitness_threshold: float = 0.0,
    persist: bool = True,
    generation: int = 0,
) -> tuple[list[FactorNode], list[float], GenerationStats]:
    """Score the population, build the next generation, and (optionally)
    persist survivors above ``fitness_threshold`` to the vector store."""
    t0 = time.time()
    fitnesses, results = await _score_population(
        population,
        start=start,
        end=end,
        universe_size=universe_size,
        pre_score_filter=pre_score_filter,
    )

    new_persisted = 0
    if persist:
        new_persisted = await _persist_survivors(
            population, fitnesses, results,
            fitness_threshold=fitness_threshold, generation=generation,
        )

    next_pop = _breed_next_generation(
        population, fitnesses, rng=rng,
        elite_frac=elite_frac, tournament_k=tournament_k,
        crossover_rate=crossover_rate, mutation_rate=mutation_rate,
    )

    finite_fits = [f for f in fitnesses if f > _SKIPPED_FITNESS]
    stats = GenerationStats(
        generation=generation,
        population_size=len(population),
        best_fitness=max(finite_fits) if finite_fits else _SKIPPED_FITNESS,
        median_fitness=float(np.median(finite_fits)) if finite_fits else _SKIPPED_FITNESS,
        new_persisted=new_persisted,
        elapsed_sec=time.time() - t0,
    )
    return next_pop, fitnesses, stats


# ---------------------------------------------------------------------------
# Two-stage evolution
# ---------------------------------------------------------------------------


def _seed_population(
    rng: random.Random, target_size: int, max_depth: int = 4
) -> list[FactorNode]:
    seeds = get_seed_population()
    pop = list(seeds)[:target_size]
    while len(pop) < target_size:
        pop.append(random_tree(rng, max_depth=max_depth))
    return pop


def _build_stage2_population(
    stage1_pop: Sequence[FactorNode],
    stage1_fits: Sequence[float],
    *,
    rng: random.Random,
    target_size: int,
    elite_carry: int = 20,
) -> list[FactorNode]:
    seeds = get_seed_population()
    sorted_idx = sorted(range(len(stage1_pop)), key=lambda i: stage1_fits[i], reverse=True)
    elite = [stage1_pop[i] for i in sorted_idx[:elite_carry]]
    pop2 = list(elite)
    while len(pop2) < target_size:
        if rng.random() < 0.3 and seeds:
            pop2.append(rng.choice(seeds))
        else:
            pop2.append(random_tree(rng, max_depth=4))
    return pop2


async def _run_stage(
    population: list[FactorNode],
    *,
    start: date,
    end: date,
    rng: random.Random,
    n_gens: int,
    universe_size: int,
    fitness_threshold: float,
    pre_score_filter: Optional[Callable[[FactorNode], float]],
    base_generation: int,
    stage_label: str,
) -> tuple[list[FactorNode], list[float], list[GenerationStats]]:
    stats_log: list[GenerationStats] = []
    fits: list[float] = []
    for g in range(n_gens):
        population, fits, stats = await run_generation(
            population, start=start, end=end, rng=rng,
            universe_size=universe_size,
            fitness_threshold=fitness_threshold,
            pre_score_filter=pre_score_filter,
            generation=base_generation + g,
        )
        stats_log.append(stats)
        logger.info(
            "[%s g=%d] best=%.4f median=%.4f persisted=%d (%.1fs)",
            stage_label, g, stats.best_fitness, stats.median_fitness,
            stats.new_persisted, stats.elapsed_sec,
        )
    return population, fits, stats_log


async def run_two_stage_evolution(
    *,
    end: date,
    seed: int = 42,
    stage1_pop: int = 50,
    stage1_gens: int = 5,
    stage1_years: int = 2,
    stage2_pop: int = 100,
    stage2_gens: int = 5,
    stage2_years: int = 5,
    universe_size: int = 100,
    fitness_threshold: float = 0.02,
    pre_score_filter: Optional[Callable[[FactorNode], float]] = None,
) -> EvolutionResult:
    """Stage 1 explores on a smaller universe / shorter window; the elite
    carry into Stage 2 which scores on a longer window. Survivors are
    accumulated in the vector store as each generation runs."""
    rng = random.Random(seed)

    pop = _seed_population(rng, stage1_pop)
    s1_start, s1_end = _sample_panel_window(end, stage1_years)
    pop, fits1, stage_1_stats = await _run_stage(
        pop, start=s1_start, end=s1_end, rng=rng,
        n_gens=stage1_gens, universe_size=universe_size,
        fitness_threshold=fitness_threshold,
        pre_score_filter=pre_score_filter,
        base_generation=0, stage_label="Stage 1",
    )

    pop2 = _build_stage2_population(pop, fits1, rng=rng, target_size=stage2_pop)
    s2_start, s2_end = _sample_panel_window(end, stage2_years)
    pop2, fits2, stage_2_stats = await _run_stage(
        pop2, start=s2_start, end=s2_end, rng=rng,
        n_gens=stage2_gens, universe_size=universe_size,
        fitness_threshold=fitness_threshold,
        pre_score_filter=pre_score_filter,
        base_generation=stage1_gens, stage_label="Stage 2",
    )

    sorted2 = sorted(range(len(pop2)), key=lambda i: fits2[i], reverse=True)
    top_survivors = [
        serialize(pop2[i]) for i in sorted2 if fits2[i] >= fitness_threshold
    ][:20]

    return EvolutionResult(
        stage_1_stats=stage_1_stats,
        stage_2_stats=stage_2_stats,
        survivors=top_survivors,
    )


__all__ = [
    "EvolutionResult",
    "GenerationStats",
    "run_generation",
    "run_two_stage_evolution",
]
