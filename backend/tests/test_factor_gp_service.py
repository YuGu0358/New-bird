"""Integration tests for ``app.services.factor_gp_service``.

The backtest engine and vector store are stubbed out so the test runs
in-memory and deterministically. We verify:

  * elite carries forward across generations,
  * fitnesses are produced for every candidate,
  * survivors above ``fitness_threshold`` are pushed to the vector store,
  * the two-stage driver wires its inputs/outputs correctly.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pytest

from core.factors import parse, serialize
from core.factors.genetic import random_tree
from app.services import factor_gp_service


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StubResult:
    fitness: float
    ic_1d: float = 0.01
    ic_5d: float = 0.02
    ic_20d: float = 0.03
    icir_5d: float = 0.5
    sharpe: float = 1.0
    max_drawdown: float = -0.1
    turnover: float = 0.05
    return_curve: list = field(default_factory=lambda: [1.0] * 64)


def _fitness_from_formula(formula: str) -> float:
    """Deterministic fitness keyed on formula length so longer formulas score
    slightly better. Bounded so the elite ordering is stable across runs."""
    return min(0.5, 0.001 * len(formula))


@pytest.fixture
def patched_services(monkeypatch):
    """Patch backtest + vector-store calls. Captures every persisted formula."""
    persisted: list[str] = []

    async def fake_backtest(formula, *, start, end, universe_size=100, **kw):
        text = serialize(formula) if hasattr(formula, "op") else str(formula)
        return _StubResult(fitness=_fitness_from_formula(text))

    async def fake_add(formula, *, fitness, **kwargs):
        persisted.append(formula)
        return len(persisted)  # stand-in primary key

    def fake_embed_returns(arr, dim=64):
        return np.zeros(dim, dtype=np.float32)

    monkeypatch.setattr(
        factor_gp_service.factor_backtest_service,
        "backtest_factor",
        fake_backtest,
    )
    monkeypatch.setattr(
        factor_gp_service.factor_vector_store, "add_factor", fake_add
    )
    monkeypatch.setattr(
        factor_gp_service.factor_vector_store,
        "embed_return_series",
        fake_embed_returns,
    )
    return persisted


# ---------------------------------------------------------------------------
# run_generation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_generation_scores_every_candidate(patched_services):
    rng = random.Random(0)
    pop = [random_tree(rng, max_depth=3) for _ in range(10)]
    next_pop, fits, stats, results = await factor_gp_service.run_generation(
        pop,
        start=date(2024, 1, 1),
        end=date(2024, 6, 30),
        rng=rng,
        universe_size=20,
        fitness_threshold=0.0,
        generation=0,
    )
    assert len(fits) == len(pop)
    assert len(next_pop) == len(pop)
    assert len(results) == len(pop)
    assert stats.population_size == len(pop)
    assert stats.best_fitness >= stats.median_fitness


@pytest.mark.asyncio
async def test_run_generation_persists_above_threshold(patched_services):
    rng = random.Random(1)
    # Make all fitnesses comfortably above threshold by using long seed formulas.
    pop = [parse("rank(delta(close,5))") for _ in range(5)]
    await factor_gp_service.run_generation(
        pop,
        start=date(2024, 1, 1),
        end=date(2024, 6, 30),
        rng=rng,
        universe_size=20,
        fitness_threshold=0.0,
        persist=True,
        generation=0,
    )
    assert len(patched_services) == 5
    assert all(p == "rank(delta(close,5))" for p in patched_services)


@pytest.mark.asyncio
async def test_run_generation_skips_persistence_below_threshold(patched_services):
    rng = random.Random(2)
    pop = [parse("rank(delta(close,5))") for _ in range(3)]
    await factor_gp_service.run_generation(
        pop,
        start=date(2024, 1, 1),
        end=date(2024, 6, 30),
        rng=rng,
        universe_size=20,
        fitness_threshold=10.0,  # impossibly high
        persist=True,
        generation=0,
    )
    assert patched_services == []


@pytest.mark.asyncio
async def test_run_generation_preserves_elite(patched_services):
    """The fittest formula in gen N must reappear in gen N+1's population."""
    rng = random.Random(3)
    long_formula = parse(
        "neg(correlation(rank(delta(log(volume),2)),rank(div(sub(close,open),open)),6))"
    )
    short_formula = parse("rank(close)")
    # Mix one clear winner (long) with several losers (short).
    pop = [long_formula] + [short_formula for _ in range(9)]
    next_pop, _fits, _stats, _results = await factor_gp_service.run_generation(
        pop,
        start=date(2024, 1, 1),
        end=date(2024, 6, 30),
        rng=rng,
        elite_frac=0.2,
        fitness_threshold=-1.0,
        persist=False,
        generation=0,
    )
    expected_winner = serialize(long_formula)
    assert any(serialize(c) == expected_winner for c in next_pop)


# ---------------------------------------------------------------------------
# run_two_stage_evolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_stage_evolution_completes(patched_services):
    result = await factor_gp_service.run_two_stage_evolution(
        end=date(2024, 12, 31),
        seed=7,
        stage1_pop=8,
        stage1_gens=2,
        stage1_years=1,
        stage2_pop=10,
        stage2_gens=2,
        stage2_years=2,
        universe_size=10,
        fitness_threshold=-1.0,  # accept everything
    )
    assert len(result.stage_1_stats) == 2
    assert len(result.stage_2_stats) == 2
    # Some survivors must have been emitted (every candidate beats threshold).
    assert len(result.survivors) > 0
    # Persistence layer was invoked.
    assert len(patched_services) > 0


@pytest.mark.asyncio
async def test_two_stage_evolution_filters_survivors(patched_services):
    """Threshold above the max possible stub fitness yields zero survivors."""
    result = await factor_gp_service.run_two_stage_evolution(
        end=date(2024, 12, 31),
        seed=11,
        stage1_pop=6,
        stage1_gens=1,
        stage1_years=1,
        stage2_pop=6,
        stage2_gens=1,
        stage2_years=1,
        universe_size=10,
        fitness_threshold=10.0,
    )
    assert result.survivors == []
    assert patched_services == []
