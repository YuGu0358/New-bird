"""Recursive evaluator for factor ASTs against a panel DataFrame."""

from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

from .ast import FactorNode, COLUMN_TOKENS
from .ops import OPS

logger = logging.getLogger(__name__)


def _nan_series(panel: pd.DataFrame) -> pd.Series:
    return pd.Series(np.nan, index=panel.index, name="factor")


def _resolve_leaf(arg: Any, panel: pd.DataFrame) -> Any:
    """Resolve a primitive arg (column name / number) against the panel."""
    if isinstance(arg, (int, float)):
        return arg
    if isinstance(arg, str):
        if arg not in COLUMN_TOKENS:
            raise ValueError(f"Unknown column token {arg!r}")
        if arg not in panel.columns:
            raise KeyError(
                f"Column {arg!r} not present in panel (have {list(panel.columns)})"
            )
        return panel[arg]
    raise TypeError(f"Cannot resolve leaf of type {type(arg).__name__}")


def _eval(
    node: FactorNode,
    panel: pd.DataFrame,
    cache: Dict[int, pd.Series],
) -> pd.Series:
    key = id(node)
    if key in cache:
        return cache[key]

    op_name = node.op
    if op_name not in OPS:
        raise ValueError(f"Unknown operator {op_name!r}")

    try:
        evaluated_args = []
        for arg in node.args:
            if isinstance(arg, FactorNode):
                evaluated_args.append(_eval(arg, panel, cache))
            else:
                evaluated_args.append(_resolve_leaf(arg, panel))
        result = OPS[op_name](*evaluated_args)
        if isinstance(result, pd.Series) and not result.index.equals(panel.index):
            # try to reindex if shapes are compatible; otherwise NaN-fill
            try:
                result = result.reindex(panel.index)
            except Exception:  # noqa: BLE001
                result = _nan_series(panel)
        if not isinstance(result, pd.Series):
            # broadcast scalar to panel
            result = pd.Series(
                np.full(len(panel.index), float(result), dtype=float),
                index=panel.index,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Factor eval failed at %s: %s", op_name, exc)
        result = _nan_series(panel)

    cache[key] = result
    return result


def evaluate(node: FactorNode, panel: pd.DataFrame) -> pd.Series:
    """Compute factor values for every (date, symbol) cell.

    Parameters
    ----------
    node : FactorNode
        Root of the factor expression tree.
    panel : pd.DataFrame
        MultiIndex ``(date, symbol)`` panel with the OHLCV / extra columns
        referenced by the expression.

    Returns
    -------
    pd.Series
        A series indexed identically to ``panel``. Cells where any subtree
        raised an exception are filled with ``NaN``  the caller is
        responsible for NaN-aware downstream metrics.
    """
    if not isinstance(panel.index, pd.MultiIndex):
        raise ValueError("Panel must have a MultiIndex (date, symbol)")
    expected_levels = {"date", "symbol"}
    if expected_levels - set(panel.index.names):
        raise ValueError(
            f"Panel index must include levels {expected_levels}; got {panel.index.names}"
        )

    cache: Dict[int, pd.Series] = {}
    result = _eval(node, panel, cache)
    if not isinstance(result, pd.Series):
        result = pd.Series(result, index=panel.index)
    result.name = "factor"
    return result
