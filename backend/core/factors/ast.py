"""Factor expression AST.

A :class:`FactorNode` is a frozen dataclass representing a node in a factor
expression tree. Leaves carry primitive args (column-reference strings,
ints, floats); internal nodes wrap an operator name and a tuple of child
nodes / primitives.

The string serialization is an S-expression-like form:

    rank(delta(close,5))
    neg(correlation(rank(open),rank(volume),10))

Whitespace between tokens is ignored on parse and never emitted on
serialise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator, Tuple, Union

# ---------------------------------------------------------------------------
# Column whitelist  any unknown lowercase identifier raises at parse time
# ---------------------------------------------------------------------------

COLUMN_TOKENS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "returns",
        "vwap",
        "sector",
        "mcap",
        "news_sent",
        "news_count",
    }
)


@dataclass(frozen=True)
class FactorNode:
    """An immutable factor expression node."""

    op: str
    args: Tuple[Any, ...]

    def __str__(self) -> str:
        return serialize(self)


NodeOrPrim = Union[FactorNode, str, int, float]


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _format_arg(arg: Any) -> str:
    if isinstance(arg, FactorNode):
        return serialize(arg)
    if isinstance(arg, bool):
        return "1" if arg else "0"
    if isinstance(arg, int):
        return str(arg)
    if isinstance(arg, float):
        # avoid trailing zeros while keeping enough precision
        if arg == int(arg):
            return str(int(arg))
        return repr(arg)
    if isinstance(arg, str):
        return arg
    raise TypeError(f"Unsupported arg type: {type(arg).__name__}")


def serialize(node: FactorNode) -> str:
    """Render a node to its canonical string form."""
    parts = [_format_arg(a) for a in node.args]
    return f"{node.op}({','.join(parts)})"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse(s: str) -> FactorNode:
    """Parse a serialised factor expression back into a :class:`FactorNode`."""
    text = s.strip()
    if not text:
        raise ValueError("Empty factor expression")
    node, idx = _parse_expr(text, 0)
    # consume trailing whitespace
    while idx < len(text) and text[idx].isspace():
        idx += 1
    if idx != len(text):
        raise ValueError(f"Trailing characters at offset {idx}: {text[idx:]!r}")
    if not isinstance(node, FactorNode):
        raise ValueError("Top-level expression must be a function call")
    return node


def _skip_ws(text: str, idx: int) -> int:
    while idx < len(text) and text[idx].isspace():
        idx += 1
    return idx


def _parse_expr(text: str, idx: int) -> Tuple[NodeOrPrim, int]:
    idx = _skip_ws(text, idx)
    if idx >= len(text):
        raise ValueError("Unexpected end of expression")

    ch = text[idx]
    # number (int / float, optionally signed)
    if ch.isdigit() or ch == "-" or ch == "+":
        return _parse_number(text, idx)

    # identifier  either column ref or function call
    if ch.isalpha() or ch == "_":
        return _parse_identifier(text, idx)

    raise ValueError(f"Unexpected character {ch!r} at offset {idx}")


def _parse_number(text: str, idx: int) -> Tuple[Union[int, float], int]:
    start = idx
    if text[idx] in "+-":
        idx += 1
    has_digit = False
    while idx < len(text) and (text[idx].isdigit() or text[idx] == "."):
        has_digit = True
        idx += 1
    # exponent
    if idx < len(text) and text[idx] in "eE":
        idx += 1
        if idx < len(text) and text[idx] in "+-":
            idx += 1
        while idx < len(text) and text[idx].isdigit():
            idx += 1
    raw = text[start:idx]
    if not has_digit:
        raise ValueError(f"Invalid number at offset {start}: {raw!r}")
    if "." in raw or "e" in raw or "E" in raw:
        return float(raw), idx
    return int(raw), idx


def _parse_identifier(text: str, idx: int) -> Tuple[NodeOrPrim, int]:
    start = idx
    while idx < len(text) and (text[idx].isalnum() or text[idx] == "_"):
        idx += 1
    name = text[start:idx]
    idx = _skip_ws(text, idx)

    if idx < len(text) and text[idx] == "(":
        # function call
        idx += 1  # consume '('
        args: list = []
        idx = _skip_ws(text, idx)
        if idx < len(text) and text[idx] == ")":
            idx += 1
            return FactorNode(name, tuple(args)), idx
        while True:
            arg, idx = _parse_expr(text, idx)
            args.append(arg)
            idx = _skip_ws(text, idx)
            if idx >= len(text):
                raise ValueError("Unterminated argument list")
            if text[idx] == ",":
                idx += 1
                continue
            if text[idx] == ")":
                idx += 1
                break
            raise ValueError(
                f"Expected ',' or ')' at offset {idx}, found {text[idx]!r}"
            )
        return FactorNode(name, tuple(args)), idx

    # bare identifier  must be a known column token
    if name not in COLUMN_TOKENS:
        raise ValueError(
            f"Unknown column token {name!r}; allowed: {sorted(COLUMN_TOKENS)}"
        )
    return name, idx


# ---------------------------------------------------------------------------
# Tree utilities
# ---------------------------------------------------------------------------


def depth(node: FactorNode) -> int:
    """Return the depth of the AST (a leaf op with no FactorNode children = 1)."""
    if not isinstance(node, FactorNode):
        return 0
    inner = [depth(a) for a in node.args if isinstance(a, FactorNode)]
    return 1 + max(inner, default=0)


def node_count(node: FactorNode) -> int:
    """Return the count of FactorNode instances in the tree."""
    if not isinstance(node, FactorNode):
        return 0
    return 1 + sum(node_count(a) for a in node.args if isinstance(a, FactorNode))


def walk(
    node: FactorNode,
) -> Generator[Tuple[FactorNode, int, FactorNode], None, None]:
    """Yield ``(parent, child_index, child_node)`` for every FactorNode child."""
    if not isinstance(node, FactorNode):
        return
    for i, child in enumerate(node.args):
        if isinstance(child, FactorNode):
            yield node, i, child
            yield from walk(child)


def replace_subtree(
    node: FactorNode, path: Tuple[int, ...], new_node: NodeOrPrim
) -> FactorNode:
    """Return a copy of ``node`` with the subtree at ``path`` replaced.

    ``path`` is a sequence of child indices descending from the root. An
    empty path replaces the root itself  in that case ``new_node`` must be a
    :class:`FactorNode`.
    """
    if not path:
        if not isinstance(new_node, FactorNode):
            raise ValueError("Cannot replace root with non-FactorNode")
        return new_node
    head, *rest = path
    if head < 0 or head >= len(node.args):
        raise IndexError(f"Path index {head} out of range for op {node.op!r}")
    target = node.args[head]
    if rest:
        if not isinstance(target, FactorNode):
            raise ValueError(
                f"Cannot descend into non-FactorNode arg at index {head}"
            )
        replaced = replace_subtree(target, tuple(rest), new_node)
    else:
        replaced = new_node
    new_args = tuple(
        replaced if i == head else a for i, a in enumerate(node.args)
    )
    return FactorNode(node.op, new_args)
