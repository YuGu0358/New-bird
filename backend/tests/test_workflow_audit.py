"""Audit log behavior for the workflow paper-order hook.

These tests exercise the ``_default_paper_order`` audit-row contract:

- A row is written when a dispatch happens inside a workflow context
  (``_CURRENT_WORKFLOW_NAME`` set).
- No row is written when the hook is called outside that context
  (e.g., from another caller / direct test invocation).
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.database import AsyncSessionLocal, init_database
from app.db.tables import WorkflowRun
from app.services import workflow_service


class WorkflowAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await init_database()

    async def test_paper_order_writes_audit_row(self) -> None:
        token = workflow_service._CURRENT_WORKFLOW_NAME.set("audit-test-flow")
        try:
            payload = {"side": "buy", "qty": 10, "paper": True, "symbol": "AAPL"}
            # Stub Alpaca so the test never touches the network; the audit
            # hook still fires regardless of the broker's response.
            fake = AsyncMock(return_value={"id": "stub-1"})
            with patch("app.services.alpaca_service.submit_order", fake):
                await workflow_service._default_paper_order(payload)
        finally:
            workflow_service._CURRENT_WORKFLOW_NAME.reset(token)

        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(WorkflowRun).where(
                        WorkflowRun.workflow_name == "audit-test-flow"
                    )
                )
            ).scalars().all()

        self.assertGreaterEqual(len(rows), 1)
        latest = rows[-1]
        self.assertEqual(latest.symbol, "AAPL")
        self.assertEqual(latest.side, "buy")
        self.assertEqual(latest.qty, 10.0)

    async def test_no_audit_when_outside_workflow_context(self) -> None:
        async with AsyncSessionLocal() as session:
            before = (
                await session.execute(select(WorkflowRun))
            ).scalars().all()

        # No context var set — hook should be a silent no-op.
        fake = AsyncMock(return_value={"id": "stub-2"})
        with patch("app.services.alpaca_service.submit_order", fake):
            await workflow_service._default_paper_order(
                {"side": "buy", "qty": 1, "symbol": "TSLA"}
            )

        async with AsyncSessionLocal() as session:
            after = (
                await session.execute(select(WorkflowRun))
            ).scalars().all()

        self.assertEqual(len(after), len(before))


if __name__ == "__main__":
    unittest.main()
