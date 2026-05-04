"""Factor Forge: factor mining operator library, AST, and evaluator.

Public API:
    - ``FactorNode``  immutable factor expression tree node
    - ``serialize`` / ``parse``  string roundtrip for AST nodes
    - ``evaluate``  vectorised evaluation of a node against a panel DataFrame
    - ``OPS``  registry of vectorised operator callables (~40)
    - ``SEEDS`` / ``get_seed_population``  WorldQuant Alpha 101 seed factors
"""

from .ast import (
    FactorNode,
    COLUMN_TOKENS,
    serialize,
    parse,
    depth,
    node_count,
    walk,
    replace_subtree,
)
from .ops import OPS
from .eval import evaluate
from .seeds import SEEDS, get_seed_population

__all__ = [
    "FactorNode",
    "COLUMN_TOKENS",
    "serialize",
    "parse",
    "depth",
    "node_count",
    "walk",
    "replace_subtree",
    "OPS",
    "evaluate",
    "SEEDS",
    "get_seed_population",
]
