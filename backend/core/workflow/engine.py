"""Workflow execution engine — topological-sort runner over a node graph.

Pure compute: no FastAPI, no DB, no broker side effects. Callers inject
the three IO hooks (``fetcher``, ``indicator_fn``, ``paper_order_fn``)
so the engine itself is fully deterministic and trivially testable.

Node types (must mirror the React Flow JSON the frontend produces):
- ``data-fetch``  : pulls a price series via ``fetcher``.
- ``indicator``   : computes one technical indicator on the upstream
                    series via ``indicator_fn``.
- ``signal``      : evaluates a boolean expression over names harvested
                    from upstream node outputs.
                    SECURITY: never uses ``eval()`` — see
                    ``core/workflow/safe_eval.py``.
- ``risk-check``  : deterministic stub (Phase 5.6 MVP) that approves or
                    rejects based on ``max_position_size`` against a
                    hardcoded baseline ``current_position=0``.
- ``order``       : if any upstream signal/risk-check produced a
                    block-condition, skips. Otherwise dispatches via
                    ``paper_order_fn`` (which the service-layer wires to
                    a no-op log call for the MVP — no real broker call).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from core.workflow.safe_eval import safe_eval_expression


VALID_NODE_TYPES = frozenset(
    {"data-fetch", "indicator", "signal", "risk-check", "order"}
)


class Fetcher(Protocol):
    """Async callable returning a price series for a ticker."""

    async def __call__(self, ticker: str, lookback_days: int) -> list[float]: ...


IndicatorFn = Callable[[str, int, list[float]], list[float | None]]
PaperOrderFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class NodeResult:
    """Per-node execution outcome.

    ``output`` is empty when ``error`` is set. ``error`` is None on
    success. Both are JSON-serialisable so the runner can return them
    over HTTP without further massage.
    """

    node_id: str
    node_type: str
    output: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True)
class WorkflowRunResult:
    nodes: list[NodeResult]
    final_output: dict[str, Any]
    succeeded: bool
    duration_ms: int


@dataclass(frozen=True)
class _Node:
    id: str
    type: str
    data: dict[str, Any]


@dataclass
class _Context:
    """Mutable per-run state: node lookups, edge maps, completed outputs."""

    nodes_by_id: dict[str, _Node]
    parents: dict[str, list[str]]
    children: dict[str, list[str]]
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _parse_definition(definition: dict[str, Any]) -> _Context:
    """Validate the React Flow JSON shape into a workable _Context.

    Raises ValueError on structural problems — the caller catches and
    folds it into a single failed-NodeResult.
    """
    if not isinstance(definition, dict):
        raise ValueError("definition must be a dict")

    raw_nodes = definition.get("nodes", [])
    raw_edges = definition.get("edges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise ValueError("nodes and edges must be lists")

    nodes_by_id: dict[str, _Node] = {}
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            raise ValueError("each node must be an object")
        node_id = raw.get("id")
        node_type = raw.get("type")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("node.id must be a non-empty string")
        if node_type not in VALID_NODE_TYPES:
            raise ValueError(f"unknown node type: {node_type!r}")
        data = raw.get("data") or {}
        if not isinstance(data, dict):
            raise ValueError(f"node {node_id} has non-dict data")
        if node_id in nodes_by_id:
            raise ValueError(f"duplicate node id: {node_id}")
        nodes_by_id[node_id] = _Node(id=node_id, type=node_type, data=data)

    parents: dict[str, list[str]] = defaultdict(list)
    children: dict[str, list[str]] = defaultdict(list)
    for raw in raw_edges:
        if not isinstance(raw, dict):
            raise ValueError("each edge must be an object")
        src = raw.get("source")
        dst = raw.get("target")
        if src not in nodes_by_id or dst not in nodes_by_id:
            raise ValueError(f"edge references unknown node: {src} -> {dst}")
        parents[dst].append(src)
        children[src].append(dst)

    return _Context(
        nodes_by_id=nodes_by_id, parents=parents, children=children
    )


def _topological_order(ctx: _Context) -> list[str]:
    """Kahn's algorithm. Returns [] if a cycle is present."""
    indegree: dict[str, int] = {nid: 0 for nid in ctx.nodes_by_id}
    for nid, ps in ctx.parents.items():
        indegree[nid] = len(ps)

    queue: deque[str] = deque(nid for nid, deg in indegree.items() if deg == 0)
    order: list[str] = []
    while queue:
        nid = queue.popleft()
        order.append(nid)
        for child in ctx.children.get(nid, []):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(order) != len(ctx.nodes_by_id):
        return []
    return order


def _ancestor_outputs(
    ctx: _Context, node_id: str
) -> dict[str, dict[str, Any]]:
    """Walk parents transitively, collecting their successful outputs.

    The signal node uses this to harvest names like ``rsi`` or
    ``matched`` regardless of how many hops upstream they came from.
    """
    seen: set[str] = set()
    queue: deque[str] = deque(ctx.parents.get(node_id, []))
    collected: dict[str, dict[str, Any]] = {}
    while queue:
        pid = queue.popleft()
        if pid in seen:
            continue
        seen.add(pid)
        if pid in ctx.outputs:
            collected[pid] = ctx.outputs[pid]
        queue.extend(ctx.parents.get(pid, []))
    return collected


def _find_upstream_prices(
    ctx: _Context, node_id: str
) -> list[float] | None:
    """First (BFS-closest) upstream data-fetch node's prices, if any."""
    for parent_out in _ancestor_outputs(ctx, node_id).values():
        prices = parent_out.get("prices")
        if isinstance(prices, list):
            return [float(p) for p in prices]
    return None


def _block_reason_from_upstream(
    ctx: _Context, node_id: str
) -> str | None:
    """Inspect ancestors for an explicit block signal (signal=False or
    risk-check ok=False). Returns a human-friendly reason, or None when
    nothing upstream blocks the flow."""
    for pid, payload in _ancestor_outputs(ctx, node_id).items():
        parent = ctx.nodes_by_id.get(pid)
        if parent is None:
            continue
        if parent.type == "signal" and payload.get("matched") is False:
            return f"signal {pid} did not match"
        if parent.type == "risk-check" and payload.get("ok") is False:
            return f"risk-check {pid} blocked: {payload.get('reason', '')}"
    return None


# --- Per-node executors --------------------------------------------------

async def _run_data_fetch(
    node: _Node, fetcher: Fetcher
) -> dict[str, Any]:
    ticker = node.data.get("ticker")
    lookback = int(node.data.get("lookback_days", 30))
    if not isinstance(ticker, str) or not ticker:
        raise ValueError("data-fetch.data.ticker must be a non-empty string")
    if lookback <= 0:
        raise ValueError("data-fetch.data.lookback_days must be > 0")
    prices = await fetcher(ticker, lookback)
    return {"ticker": ticker, "prices": [float(p) for p in prices]}


def _run_indicator(
    node: _Node, ctx: _Context, indicator_fn: IndicatorFn
) -> dict[str, Any]:
    name = node.data.get("name")
    period = int(node.data.get("period", 14))
    if not isinstance(name, str) or not name:
        raise ValueError("indicator.data.name must be a non-empty string")
    prices = _find_upstream_prices(ctx, node.id)
    if prices is None:
        raise ValueError("indicator node has no upstream data-fetch prices")
    series = indicator_fn(name, period, prices)
    last_value: float | None = None
    for v in reversed(series):
        if v is not None:
            last_value = float(v)
            break
    return {name: last_value, "series_len": len(series)}


def _run_signal(node: _Node, ctx: _Context) -> dict[str, Any]:
    expression = node.data.get("expr")
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("signal.data.expr must be a non-empty string")
    names: dict[str, Any] = {}
    for payload in _ancestor_outputs(ctx, node.id).values():
        for key, value in payload.items():
            # Only forward simple scalars usable in expressions; skip
            # raw price arrays and other complex structures.
            if isinstance(value, (int, float, bool, str)) or value is None:
                names[key] = value
    matched = bool(safe_eval_expression(expression, names))
    return {"matched": matched, "expr": expression}


def _run_risk_check(node: _Node) -> dict[str, Any]:
    """Deterministic MVP stub: compares max_position_size to a baseline 0.

    Real risk integration is a follow-up — the wiring matters more than
    the policy at this phase.
    """
    max_size = node.data.get("max_position_size")
    current_position = 0  # MVP baseline; real code reads from broker.
    if max_size is None:
        return {"ok": True, "reason": "no max_position_size configured"}
    try:
        max_size_f = float(max_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("risk-check.data.max_position_size must be numeric") from exc
    if current_position > max_size_f:
        return {
            "ok": False,
            "reason": (
                f"current_position {current_position} exceeds "
                f"max_position_size {max_size_f}"
            ),
        }
    return {"ok": True, "reason": ""}


async def _run_order(
    node: _Node, ctx: _Context, paper_order_fn: PaperOrderFn
) -> dict[str, Any]:
    block = _block_reason_from_upstream(ctx, node.id)
    if block is not None:
        return {"skipped": True, "reason": block}
    side = node.data.get("side")
    qty = node.data.get("qty")
    paper = bool(node.data.get("paper", True))
    if side not in {"buy", "sell"}:
        raise ValueError("order.data.side must be 'buy' or 'sell'")
    try:
        qty_f = float(qty)
    except (TypeError, ValueError) as exc:
        raise ValueError("order.data.qty must be numeric") from exc
    if qty_f <= 0:
        raise ValueError("order.data.qty must be > 0")

    # Inherit ticker from the closest upstream data-fetch node so the order
    # dispatcher knows which symbol to send. Node-local override wins.
    ticker = node.data.get("ticker")
    if not ticker:
        for parent_out in _ancestor_outputs(ctx, node.id).values():
            t = parent_out.get("ticker")
            if isinstance(t, str) and t:
                ticker = t
                break

    payload: dict[str, Any] = {"side": side, "qty": qty_f, "paper": paper}
    if ticker:
        payload["symbol"] = ticker
    dispatch_result = await paper_order_fn(payload)
    return {**payload, "dispatched": True, "broker_response": dispatch_result}


# --- Public entrypoint ---------------------------------------------------

async def execute_workflow(
    definition: dict[str, Any],
    *,
    fetcher: Fetcher,
    indicator_fn: IndicatorFn,
    paper_order_fn: PaperOrderFn,
) -> WorkflowRunResult:
    """Run a workflow definition top-down in topological order.

    SECURITY: Signal expressions are evaluated by the AST-walker in
    ``core.workflow.safe_eval`` — this function never calls Python's
    builtin ``eval()``.

    Per-node exceptions are caught and surfaced as ``NodeResult.error``;
    ``succeeded`` is False if any node errored OR if structural
    validation / cycle detection failed. The remaining nodes still run
    so the user sees as much of the partial execution as possible.
    """
    started_at = time.perf_counter()

    try:
        ctx = _parse_definition(definition)
    except ValueError as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return WorkflowRunResult(
            nodes=[
                NodeResult(
                    node_id="<definition>",
                    node_type="<invalid>",
                    output={},
                    error=str(exc),
                )
            ],
            final_output={},
            succeeded=False,
            duration_ms=duration_ms,
        )

    order = _topological_order(ctx)
    if not order and ctx.nodes_by_id:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return WorkflowRunResult(
            nodes=[
                NodeResult(
                    node_id="<graph>",
                    node_type="<cycle>",
                    output={},
                    error="cycle detected in workflow graph",
                )
            ],
            final_output={},
            succeeded=False,
            duration_ms=duration_ms,
        )

    results: list[NodeResult] = []
    succeeded = True
    for node_id in order:
        node = ctx.nodes_by_id[node_id]
        try:
            output = await _dispatch(node, ctx, fetcher, indicator_fn, paper_order_fn)
            ctx.outputs[node_id] = output
            results.append(
                NodeResult(node_id=node_id, node_type=node.type, output=output)
            )
        except Exception as exc:  # noqa: BLE001 — catch wide; wrap in NodeResult
            succeeded = False
            message = f"{type(exc).__name__}: {exc}"
            ctx.errors[node_id] = message
            results.append(
                NodeResult(
                    node_id=node_id,
                    node_type=node.type,
                    output={},
                    error=message,
                )
            )

    final_output = results[-1].output if results else {}
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    return WorkflowRunResult(
        nodes=results,
        final_output=final_output,
        succeeded=succeeded,
        duration_ms=duration_ms,
    )


async def _dispatch(
    node: _Node,
    ctx: _Context,
    fetcher: Fetcher,
    indicator_fn: IndicatorFn,
    paper_order_fn: PaperOrderFn,
) -> dict[str, Any]:
    if node.type == "data-fetch":
        return await _run_data_fetch(node, fetcher)
    if node.type == "indicator":
        return _run_indicator(node, ctx, indicator_fn)
    if node.type == "signal":
        return _run_signal(node, ctx)
    if node.type == "risk-check":
        return _run_risk_check(node)
    if node.type == "order":
        return await _run_order(node, ctx, paper_order_fn)
    raise ValueError(f"unhandled node type: {node.type}")
