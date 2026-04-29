"""Tiny safe expression evaluator used by the `signal` workflow node.

We deliberately avoid Python's built-in ``eval()`` — even with
restricted globals it has a long history of sandbox escapes via
``__class__``/``__mro__``/``__subclasses__`` traversal. Instead we
parse the expression to an AST and walk a strict allow-list.

Supported nodes:
- ``Compare`` (==, !=, <, <=, >, >=)
- ``BoolOp`` (and / or)
- ``BinOp`` (+ - * / // %)
- ``UnaryOp`` (-x, +x, not x)
- ``Constant`` (numbers, strings, True/False/None)
- ``Name`` (looked up in the supplied ``names`` mapping)

Anything else — function calls, attribute access, subscripts,
comprehensions, lambdas, walrus, f-strings — raises ``ValueError``.

This is intentionally far less capable than ``simpleeval``; it covers
the MVP's threshold-style expressions like ``rsi < 30 and matched``.
"""
from __future__ import annotations

import ast
import operator
from typing import Any

# Whitelisted operators for each AST node category.
_BIN_OPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_CMP_OPS: dict[type[ast.cmpop], Any] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}

_UNARY_OPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}


def safe_eval_expression(expression: str, names: dict[str, Any]) -> Any:
    """Evaluate ``expression`` using only the provided ``names`` mapping.

    Raises ``ValueError`` for any disallowed AST node, unknown name, or
    parse error. Never executes arbitrary code.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("expression must be a non-empty string")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression syntax: {exc}") from exc

    return _eval_node(tree.body, names)


def _eval_node(node: ast.AST, names: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id not in names:
            raise ValueError(f"unknown name in expression: {node.id!r}")
        return names[node.id]

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported unary op: {type(node.op).__name__}")
        return op(_eval_node(node.operand, names))

    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"unsupported binary op: {type(node.op).__name__}")
        return op(_eval_node(node.left, names), _eval_node(node.right, names))

    if isinstance(node, ast.BoolOp):
        values = [_eval_node(v, names) for v in node.values]
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in values:
                result = result and v
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for v in values:
                result = result or v
            return result
        raise ValueError(f"unsupported bool op: {type(node.op).__name__}")

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, names)
        for op_node, right_node in zip(node.ops, node.comparators):
            op = _CMP_OPS.get(type(op_node))
            if op is None:
                raise ValueError(
                    f"unsupported comparison op: {type(op_node).__name__}"
                )
            right = _eval_node(right_node, names)
            if not op(left, right):
                return False
            left = right
        return True

    raise ValueError(f"unsupported expression node: {type(node).__name__}")
