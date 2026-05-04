"""Genetic operators on factor ASTs.

All functions take and return new :class:`FactorNode` objects (immutable).
Random choices are driven by an injected ``random.Random`` so tests can be
fully deterministic.

Module relies only on the public AST helpers (``replace_subtree``,
``FactorNode``) and the operator registry (``OPS``). Operator arities are
looked up via a hand-coded fallback table because ``ops.py`` does not
export an arity map.
"""
from __future__ import annotations

import random
from typing import Any, Iterable, Sequence, Tuple

from core.factors.ast import FactorNode, replace_subtree
from core.factors.op_stats import weighted_op_choice
from core.factors.ops import OPS

# Leaf token vocabulary.
_COLUMNS: tuple[str, ...] = (
    "close", "open", "high", "low", "volume", "returns", "vwap",
    "sector", "mcap", "news_sent", "news_count",
)
_INTEGERS: tuple[int, ...] = (2, 3, 5, 10, 15, 20, 30, 60, 120)
_FLOATS: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0)

# Operator arities (fallback — ops.py exposes no introspection helper).
_OP_ARITIES: dict[str, int] = {
    "rank": 1, "zscore": 1, "min_max_scale": 1, "neg": 1, "abs": 1,
    "sign": 1, "log": 1, "sqrt": 1,
    "quantile": 2, "industry_neutral": 2, "market_cap_neutral": 2,
    "ts_mean": 2, "ts_std": 2, "ts_min": 2, "ts_max": 2, "ts_sum": 2,
    "ts_argmin": 2, "ts_argmax": 2, "ts_rank": 2, "delta": 2, "delay": 2,
    "decay_linear": 2, "ema": 2, "sma": 2,
    "add": 2, "sub": 2, "mul": 2, "div": 2, "power": 2,
    "correlation": 3, "covariance": 3, "regression_neutral": 3, "if_else": 3,
}

# Ops whose trailing arg must be an integer window — keeps random trees evaluable.
_INT_WINDOW_OPS: frozenset[str] = frozenset({
    "ts_mean", "ts_std", "ts_min", "ts_max", "ts_sum", "ts_argmin",
    "ts_argmax", "ts_rank", "delta", "delay", "decay_linear", "ema", "sma",
    "quantile",
})


def _arity_of(op_name: str) -> int:
    return _OP_ARITIES.get(op_name, 1)


# ---------------------------------------------------------------------------
# Leaf / random tree generation
# ---------------------------------------------------------------------------


def random_leaf(rng: random.Random) -> Any:
    """Random leaf: column name, int window, or float weight."""
    pool = rng.choice(("col", "int", "float"))
    if pool == "col":
        return rng.choice(_COLUMNS)
    if pool == "int":
        return rng.choice(_INTEGERS)
    return rng.choice(_FLOATS)


def random_tree(rng: random.Random, max_depth: int = 4) -> FactorNode:
    """Generate a random factor AST up to ``max_depth``.

    Operator selection is uniform over ``OPS``. For ops in
    ``_INT_WINDOW_OPS`` the trailing window arg is forced to an integer.
    """
    if max_depth <= 0:
        return _wrap_leaf_in_op(rng)
    op = rng.choice(list(OPS.keys()))
    arity = _arity_of(op)
    leaf_bias = 0.4 if max_depth > 1 else 1.0

    args: list[Any] = []
    for i in range(arity):
        if op in _INT_WINDOW_OPS and i == arity - 1:
            args.append(rng.choice(_INTEGERS))
            continue
        if rng.random() < leaf_bias:
            args.append(random_leaf(rng))
        else:
            args.append(random_tree(rng, max_depth - 1))
    return FactorNode(op=op, args=tuple(args))


def _wrap_leaf_in_op(rng: random.Random) -> FactorNode:
    """Pick an arity-1 op and feed it a column leaf (terminal subtree)."""
    arity_1_ops = [name for name in OPS if _arity_of(name) == 1]
    op = rng.choice(arity_1_ops or ["rank"])
    return FactorNode(op=op, args=(rng.choice(_COLUMNS),))


# ---------------------------------------------------------------------------
# Path utilities
# ---------------------------------------------------------------------------


def _iter_paths(node: FactorNode) -> Iterable[Tuple[int, ...]]:
    """Yield every path to a FactorNode (including the empty root path)."""
    yield ()
    if not isinstance(node, FactorNode):
        return
    for i, arg in enumerate(node.args):
        if isinstance(arg, FactorNode):
            for sub in _iter_paths(arg):
                yield (i,) + sub


def _get_subtree(node: FactorNode, path: Tuple[int, ...]) -> Any:
    cur: Any = node
    for i in path:
        if not isinstance(cur, FactorNode):
            return cur
        cur = cur.args[i]
    return cur


# ---------------------------------------------------------------------------
# Genetic operators
# ---------------------------------------------------------------------------


def crossover(
    parent_a: FactorNode, parent_b: FactorNode, rng: random.Random
) -> FactorNode:
    """Subtree crossover: splice a random FactorNode subtree from B into A."""
    paths_a = list(_iter_paths(parent_a))
    paths_b = list(_iter_paths(parent_b))
    if not paths_a or not paths_b:
        return parent_a
    path_a = rng.choice(paths_a)
    path_b = rng.choice(paths_b)
    subtree = _get_subtree(parent_b, path_b)
    if not isinstance(subtree, FactorNode):
        # The selected subtree was a primitive — fall back to whole B.
        subtree = parent_b
    return replace_subtree(parent_a, path_a, subtree)


def mutate(
    node: FactorNode,
    rng: random.Random,
    mutation_rate: float = 0.3,
    op_weights: dict[str, float] | None = None,
) -> FactorNode:
    """Random mutation. With probability ``mutation_rate``, apply one of:

      * subtree replacement — swap a random FactorNode subtree for a fresh
        random tree (depth <= 2);
      * operator swap — replace the operator at a random subtree with another
        op of the same arity, preserving its args.

    When ``op_weights`` is provided, the operator-swap branch samples by
    weight (epsilon-floored, normalized internally) instead of uniformly.
    Falls back to uniform when weights are missing or zero for the
    candidate ops.

    Otherwise return ``node`` unchanged. The original is never mutated.
    """
    if rng.random() > mutation_rate:
        return node
    paths = list(_iter_paths(node))
    if not paths:
        return random_tree(rng, max_depth=3)
    path = rng.choice(paths)

    if rng.random() < 0.5:
        return replace_subtree(node, path, random_tree(rng, max_depth=2))

    target = _get_subtree(node, path)
    if not isinstance(target, FactorNode):
        return node
    arity = _arity_of(target.op)
    same_arity_ops = [op for op in OPS if _arity_of(op) == arity and op != target.op]
    if not same_arity_ops:
        return node
    new_op = weighted_op_choice(same_arity_ops, op_weights, rng)
    return replace_subtree(node, path, FactorNode(op=new_op, args=target.args))


def tournament_select(
    population: Sequence[FactorNode],
    fitnesses: Sequence[float],
    k: int,
    rng: random.Random,
) -> FactorNode:
    """Tournament selection: sample ``k`` candidates, return the fittest."""
    n = len(population)
    if n == 0:
        raise ValueError("Empty population")
    if len(fitnesses) != n:
        raise ValueError("population/fitness length mismatch")
    indices = rng.sample(range(n), min(k, n))
    best = max(indices, key=lambda i: fitnesses[i])
    return population[best]


__all__ = [
    "crossover",
    "mutate",
    "random_leaf",
    "random_tree",
    "tournament_select",
]
