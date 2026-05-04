"""QuantaAlpha-inspired trajectory-level evolution.

Each candidate carries:
  - research_direction: short LLM-generated theme (e.g., "momentum
    reversal at 20-day support")
  - math_intuition: how the theme maps to OHLCV math (one paragraph)
  - formula: the AST string the intuition compiles down to

The evolve_trajectory() call asks the LLM to localise the failure step
(direction / intuition / formula) and rewrite ONLY that step, keeping
the rest. crossover_trajectories() blends two parents at the
intuition level, then asks the LLM to derive a new formula.

We don't depend on the upstream QuantaAlpha repo — the algorithm is
straightforward enough to re-implement using only the existing
openai_service.create_client + AST parser.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel

from app import runtime_settings
from app.db.engine import AsyncSessionLocal
from app.db.tables import FactorTrajectory
from app.services.openai_service import create_client
from core.factors.ast import parse, serialize
from core.factors.ops import OPS
from core.factors.seeds import SEEDS

logger = logging.getLogger(__name__)


@dataclass
class TrajectoryDraft:
    research_direction: str
    math_intuition: str
    formula: str
    parent_id: int | None = None
    evolution_step: str = "seed"
    fitness: float | None = None
    failure_reason: str | None = None


# ---- Pydantic schemas the LLM populates via responses.parse(text_format=) ----


class _TrajectoryResponse(BaseModel):
    research_direction: str
    math_intuition: str
    formula: str


_INSTRUCTIONS_GENERATE = (
    "You are a quantitative researcher proposing a NEW alpha factor. Produce three "
    "fields:\n"
    "1) research_direction — one sentence describing the market phenomenon you target.\n"
    "2) math_intuition — one paragraph mapping the phenomenon to OHLCV / volume / "
    "returns math.\n"
    "3) formula — an S-expression using ONLY the provided operators and column names. "
    "Depth ≤ 5. Examples: rank(ts_mean(close,20)), neg(correlation(rank(volume),rank(close),10)).\n"
    "Use deduplicated themes — if the recent factor pool already covers your idea, "
    "explore an orthogonal direction."
)

_INSTRUCTIONS_EVOLVE = (
    "You are revising an existing alpha factor. The parent's data is provided plus the "
    "failure reason from backtesting. Localise the failure step (research_direction, "
    "math_intuition, OR formula) and REWRITE ONLY THAT STEP, keeping the others "
    "intact. Output the full {research_direction, math_intuition, formula} tuple "
    "with your single revision applied."
)

_INSTRUCTIONS_CROSSOVER = (
    "You are blending two existing alpha factors into a single hybrid. Combine the "
    "two research_directions into a single coherent theme, then derive a new "
    "math_intuition and formula that captures the hybrid. Use ONLY the provided "
    "operators and columns."
)


def _model_name() -> str:
    # Factor variant generation runs many times per evolution cycle → default
    # to mini for cost. Override via runtime setting OPENAI_FACTOR_MODEL.
    return (
        runtime_settings.get_setting("OPENAI_FACTOR_MODEL", "gpt-4o-mini-2024-07-18")
        or "gpt-4o-mini-2024-07-18"
    )


def _build_grammar_prompt(*, recent_pool: list[str]) -> str:
    op_list = ", ".join(sorted(OPS.keys()))
    cols = "open, high, low, close, volume, returns, vwap, sector, mcap, news_sent, news_count"
    pool_lines = "\n".join(f"- {f}" for f in recent_pool[:10]) if recent_pool else "(empty)"
    return (
        f"Allowed operators: {op_list}\n"
        f"Allowed columns: {cols}\n"
        f"Recent pool (avoid duplication):\n{pool_lines}\n"
        f"Seed examples for reference:\n"
        + "\n".join(f"- {s}" for s in SEEDS[:5])
    )


def _llm_call_sync(instructions: str, user_prompt: str) -> _TrajectoryResponse | None:
    client = create_client()
    response = client.responses.parse(
        model=_model_name(),
        instructions=instructions,
        input=[{"role": "user", "content": user_prompt}],
        text_format=_TrajectoryResponse,
    )
    return response.output_parsed


async def _safe_llm_call(
    instructions: str, user_prompt: str
) -> _TrajectoryResponse | None:
    try:
        return await asyncio.to_thread(_llm_call_sync, instructions, user_prompt)
    except Exception:
        logger.warning("LLM trajectory call failed", exc_info=True)
        return None


def _validate_formula(formula: str) -> str | None:
    """Strip wrappers and parse to validate. Returns canonicalised string or None."""
    formula = formula.strip()
    formula = re.sub(r"^['`\"]+|['`\"]+$", "", formula)
    try:
        node = parse(formula)
    except Exception:
        return None
    return serialize(node)


async def generate_trajectory(*, recent_pool: list[str]) -> Optional[TrajectoryDraft]:
    grammar = _build_grammar_prompt(recent_pool=recent_pool)
    res = await _safe_llm_call(_INSTRUCTIONS_GENERATE, grammar)
    if res is None:
        return None
    canonical = _validate_formula(res.formula)
    if canonical is None:
        logger.info(
            "generated trajectory dropped — unparseable formula: %r",
            res.formula[:80],
        )
        return None
    return TrajectoryDraft(
        research_direction=res.research_direction.strip(),
        math_intuition=res.math_intuition.strip(),
        formula=canonical,
        evolution_step="seed",
    )


async def evolve_trajectory(
    parent: dict[str, Any],
    *,
    failure_reason: str,
    recent_pool: list[str],
) -> Optional[TrajectoryDraft]:
    """LLM rewrites the failing step in the parent trajectory."""
    grammar = _build_grammar_prompt(recent_pool=recent_pool)
    user = (
        f"PARENT:\n"
        f"  research_direction: {parent.get('research_direction')}\n"
        f"  math_intuition: {parent.get('math_intuition')}\n"
        f"  formula: {parent.get('formula')}\n"
        f"FAILURE REASON: {failure_reason}\n\n"
        f"{grammar}"
    )
    res = await _safe_llm_call(_INSTRUCTIONS_EVOLVE, user)
    if res is None:
        return None
    canonical = _validate_formula(res.formula)
    if canonical is None:
        return None
    return TrajectoryDraft(
        research_direction=res.research_direction.strip(),
        math_intuition=res.math_intuition.strip(),
        formula=canonical,
        parent_id=parent.get("id"),
        evolution_step="evolve",
        failure_reason=failure_reason,
    )


async def crossover_trajectories(
    parent_a: dict[str, Any],
    parent_b: dict[str, Any],
    *,
    recent_pool: list[str],
) -> Optional[TrajectoryDraft]:
    grammar = _build_grammar_prompt(recent_pool=recent_pool)
    user = (
        f"PARENT A:\n"
        f"  research_direction: {parent_a.get('research_direction')}\n"
        f"  math_intuition: {parent_a.get('math_intuition')}\n"
        f"  formula: {parent_a.get('formula')}\n"
        f"PARENT B:\n"
        f"  research_direction: {parent_b.get('research_direction')}\n"
        f"  math_intuition: {parent_b.get('math_intuition')}\n"
        f"  formula: {parent_b.get('formula')}\n\n"
        f"{grammar}"
    )
    res = await _safe_llm_call(_INSTRUCTIONS_CROSSOVER, user)
    if res is None:
        return None
    canonical = _validate_formula(res.formula)
    if canonical is None:
        return None
    return TrajectoryDraft(
        research_direction=res.research_direction.strip(),
        math_intuition=res.math_intuition.strip(),
        formula=canonical,
        parent_id=parent_a.get("id"),  # primary parent
        evolution_step="crossover",
    )


async def persist_trajectory(draft: TrajectoryDraft) -> int | None:
    async with AsyncSessionLocal() as session:
        row = FactorTrajectory(
            research_direction=draft.research_direction,
            math_intuition=draft.math_intuition,
            formula=draft.formula,
            parent_id=draft.parent_id,
            evolution_step=draft.evolution_step,
            fitness=draft.fitness,
            failure_reason=draft.failure_reason,
        )
        session.add(row)
        try:
            await session.commit()
            await session.refresh(row)
            return int(row.id)
        except Exception:
            await session.rollback()
            logger.warning("trajectory persist failed", exc_info=True)
            return None


async def list_trajectories(*, limit: int = 100) -> list[dict[str, Any]]:
    from sqlalchemy import desc, select

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorTrajectory)
                .order_by(desc(FactorTrajectory.created_at))
                .limit(limit)
            )
        ).scalars().all()
    return [
        {
            "id": r.id,
            "research_direction": r.research_direction,
            "math_intuition": r.math_intuition,
            "formula": r.formula,
            "parent_id": r.parent_id,
            "evolution_step": r.evolution_step,
            "fitness": r.fitness,
            "ic_5d": r.ic_5d,
            "failure_reason": r.failure_reason,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def update_trajectory_metrics(
    traj_id: int,
    *,
    fitness: float | None = None,
    ic_5d: float | None = None,
    factor_record_id: int | None = None,
    failure_reason: str | None = None,
) -> None:
    """Update a trajectory row with backtest results / promotion link."""
    from sqlalchemy import update as sql_update

    async with AsyncSessionLocal() as session:
        stmt = sql_update(FactorTrajectory).where(FactorTrajectory.id == traj_id)
        values: dict[str, Any] = {}
        if fitness is not None:
            values["fitness"] = fitness
        if ic_5d is not None:
            values["ic_5d"] = ic_5d
        if factor_record_id is not None:
            values["factor_record_id"] = factor_record_id
        if failure_reason is not None:
            values["failure_reason"] = failure_reason
        if values:
            await session.execute(stmt.values(**values))
            await session.commit()


async def list_unscored_trajectories(limit: int = 5) -> list[dict[str, Any]]:
    """Trajectories that haven't been backtested yet."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorTrajectory)
                .where(FactorTrajectory.fitness.is_(None))
                .where(FactorTrajectory.evolution_step != "crossover")
                .order_by(FactorTrajectory.id.desc())
                .limit(limit)
            )
        ).scalars().all()
    return [
        {
            "id": r.id,
            "formula": r.formula,
            "research_direction": r.research_direction,
            "evolution_step": r.evolution_step,
        }
        for r in rows
    ]


def pick_parents_for_quanta(
    library: list[dict[str, Any]],
    n: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Tournament-pick `n` parents from the library, weighted by fitness."""
    if not library:
        return []
    sorted_lib = sorted(
        library, key=lambda r: float(r.get("fitness", 0)), reverse=True
    )
    top_half = sorted_lib[: max(1, len(sorted_lib) // 2)]
    chosen: list[dict[str, Any]] = []
    for _ in range(n):
        chosen.append(rng.choice(top_half))
    return chosen
