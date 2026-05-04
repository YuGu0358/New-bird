"""Operator-success statistics for guiding GP mutation.

Bias toward operators that historically appear in high-fitness factors,
without ever zeroing-out an op (need exploration).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable


_OP_TOKEN_RE = re.compile(r"([a-zA-Z_]\w*)\s*\(")
_EPSILON = 0.01


def _ops_in_formula(formula: str) -> set[str]:
    """Pull operator tokens out of a serialized formula string."""
    return set(_OP_TOKEN_RE.findall(formula or ""))


def compute_op_weights(records: Iterable[dict]) -> dict[str, float]:
    """Average fitness per op across the library, plus epsilon floor.

    records: dicts with at least ``formula`` and ``fitness`` (or ``ic_5d``) keys.

    Returns op -> weight (positive). Missing ops get the epsilon floor.
    Result is unnormalized; consumers should normalize before sampling.
    """
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for rec in records:
        formula = rec.get("formula") or ""
        fit = rec.get("fitness")
        if fit is None:
            fit = rec.get("ic_5d") or 0.0
        try:
            fit_val = float(fit)
        except (TypeError, ValueError):
            continue
        # Floor negative fitnesses at 0 - failed factors shouldn't pull
        # weights below the exploration epsilon.
        contribution = max(fit_val, 0.0)
        for op in _ops_in_formula(formula):
            sums[op] += contribution
            counts[op] += 1
    out: dict[str, float] = {}
    for op, s in sums.items():
        avg = s / max(counts[op], 1)
        out[op] = float(avg + _EPSILON)
    return out


def weighted_op_choice(
    ops: list[str], weights: dict[str, float] | None, rng
) -> str:
    """Pick an op from ``ops`` weighted by ``weights`` (or uniform if missing)."""
    if not ops:
        raise ValueError("ops list is empty")
    if not weights:
        return rng.choice(ops)
    pool = [(op, weights.get(op, _EPSILON)) for op in ops]
    total = sum(w for _, w in pool)
    if total <= 0:
        return rng.choice(ops)
    pick = rng.random() * total
    acc = 0.0
    for op, w in pool:
        acc += w
        if pick <= acc:
            return op
    return pool[-1][0]


__all__ = ["compute_op_weights", "weighted_op_choice"]
