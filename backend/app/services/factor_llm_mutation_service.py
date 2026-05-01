"""LLM-driven creative mutation for Factor Forge GP search.

Given the top-N highest-fitness factors, asks OpenAI to propose N novel
variant formulas. Variants that fail to parse against the project AST are
silently dropped — caller is responsible for falling back to GP-only
mutation if zero variants survive.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import List

from pydantic import BaseModel

from app import runtime_settings
from app.services.openai_service import create_client
from core.factors.ast import FactorNode, parse, serialize
from core.factors.ops import OPS

logger = logging.getLogger(__name__)


class _Variant(BaseModel):
    formula: str
    rationale: str


class _VariantList(BaseModel):
    variants: list[_Variant]


_INSTRUCTIONS = (
    "You are a quantitative researcher. The user shows you the top alphas in a "
    "genetic-programming search and asks you to propose new candidate formulas "
    "that explore similar but novel territory.\n\n"
    "Constraints:\n"
    "1) Each formula must use ONLY the listed operators and column names.\n"
    "2) Operators take the exact arity shown in the seeds.\n"
    "3) Each formula uses S-expression syntax: op(arg1, arg2, ...). Nested calls "
    "allowed. Integer/float constants for window sizes and exponents.\n"
    "4) Stay under depth 6.\n"
    "5) Output structured JSON only — no markdown, no commentary in the formula field."
)


def _build_prompt(top_factors: list[dict], n_variants: int) -> str:
    """Compose the prompt: list operators, list columns, show top factors, ask for N variants."""
    op_list = ", ".join(sorted(OPS.keys()))
    col_list = (
        "open, high, low, close, volume, returns, vwap, sector, mcap, news_sent, news_count"
    )
    lines = [
        f"Available operators: {op_list}",
        f"Available column inputs: {col_list}",
        "",
        "Top alphas so far (formula → IC_5d):",
    ]
    for f in top_factors[:10]:
        lines.append(f"  {f['formula']} → {f.get('ic_5d', f.get('fitness', 0)):.4f}")
    lines.append("")
    lines.append(
        f"Propose {n_variants} novel candidate formulas that combine, extend, or invert "
        "the patterns you see above. Each variant should differ structurally (don't just "
        "tweak window sizes). Provide a one-sentence rationale per variant."
    )
    return "\n".join(lines)


def _generate_sync(prompt: str) -> _VariantList | None:
    """Single sync call — assumes openai SDK is installed and configured."""
    client = create_client()
    model_name = (
        runtime_settings.get_setting("OPENAI_FACTOR_MODEL", "gpt-4o-2024-08-06")
        or "gpt-4o-2024-08-06"
    )
    response = client.responses.parse(
        model=model_name,
        instructions=_INSTRUCTIONS,
        input=[{"role": "user", "content": prompt}],
        text_format=_VariantList,
    )
    return response.output_parsed


async def generate_variants(
    top_factors: list[dict],
    n_variants: int = 5,
) -> list[FactorNode]:
    """Public entry — returns a list of parsed FactorNodes (may be shorter than n_variants).

    top_factors: list of dicts as returned by factor_vector_store.list_factors —
                 each must have 'formula' and either 'ic_5d' or 'fitness'.
    """
    if not top_factors:
        return []
    prompt = _build_prompt(top_factors, n_variants)
    try:
        result = await asyncio.to_thread(_generate_sync, prompt)
    except Exception:
        logger.warning("OpenAI variant generation failed", exc_info=True)
        return []
    if result is None:
        return []
    out: list[FactorNode] = []
    for v in (result.variants or [])[:n_variants]:
        formula = (v.formula or "").strip()
        # Strip stray markdown / quotes the model sometimes adds.
        formula = re.sub(r"^['`\"]+|['`\"]+$", "", formula)
        try:
            node = parse(formula)
        except Exception:
            logger.info(
                "Discarding unparseable variant: %r (%s)",
                formula[:80],
                v.rationale[:80] if v.rationale else "",
            )
            continue
        out.append(node)
    return out
