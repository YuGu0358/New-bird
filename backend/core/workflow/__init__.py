"""Workflow execution engine (Phase 5.6).

Pure-Python topological-sort runner for user-built node graphs. No
FastAPI, no DB — services orchestrate, this layer just executes.
"""
from core.workflow.engine import (
    Fetcher,
    NodeResult,
    WorkflowRunResult,
    execute_workflow,
)
from core.workflow.safe_eval import safe_eval_expression

__all__ = [
    "Fetcher",
    "NodeResult",
    "WorkflowRunResult",
    "execute_workflow",
    "safe_eval_expression",
]
