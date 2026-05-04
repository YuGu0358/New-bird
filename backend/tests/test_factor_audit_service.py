"""Tests for factor_audit_service quarantine heuristics."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class FactorAuditHeuristicTests(unittest.TestCase):
    """Pure tests on ``is_suspicious`` — no DB needed."""

    def _make(self, **kw):
        from app.db.tables import FactorRecord
        defaults = dict(
            formula="rank(decay_linear(ts_std(returns,20),5))",
            fitness=0.05,
            sharpe=1.2,
            ic_5d=0.04,
            max_drawdown=0.15,
        )
        defaults.update(kw)
        return FactorRecord(**defaults)

    def test_high_sharpe_quarantined(self) -> None:
        from app.services.factor_audit_service import is_suspicious
        sus, reason = is_suspicious(self._make(sharpe=4.7))
        self.assertTrue(sus)
        self.assertIn("sharpe", reason)

    def test_negative_extreme_sharpe_quarantined(self) -> None:
        from app.services.factor_audit_service import is_suspicious
        sus, _ = is_suspicious(self._make(sharpe=-5.0))
        self.assertTrue(sus)

    def test_perfect_ic_quarantined(self) -> None:
        from app.services.factor_audit_service import is_suspicious
        sus, reason = is_suspicious(self._make(ic_5d=1.0))
        self.assertTrue(sus)
        self.assertIn("leakage", reason)

    def test_excessive_drawdown_quarantined(self) -> None:
        from app.services.factor_audit_service import is_suspicious
        sus, _ = is_suspicious(self._make(max_drawdown=0.6))
        self.assertTrue(sus)

    def test_missing_drawdown_quarantined(self) -> None:
        from app.services.factor_audit_service import is_suspicious
        sus, _ = is_suspicious(self._make(max_drawdown=None))
        self.assertTrue(sus)

    def test_trivial_formula_quarantined(self) -> None:
        from app.services.factor_audit_service import is_suspicious
        # 9 chars triggers the length branch (< 10).
        sus, reason = is_suspicious(self._make(formula="rank(o)"))
        self.assertTrue(sus)
        self.assertIn("trivial", reason)

    def test_neg_close_quarantined_by_no_timeseries(self) -> None:
        from app.services.factor_audit_service import is_suspicious
        # 10 chars passes length, but has no time-series op.
        sus, reason = is_suspicious(self._make(formula="neg(close)"))
        self.assertTrue(sus)
        self.assertIn("time-series", reason)

    def test_no_timeseries_op_quarantined(self) -> None:
        from app.services.factor_audit_service import is_suspicious
        sus, reason = is_suspicious(self._make(formula="rank(add(close,volume))"))
        self.assertTrue(sus)
        self.assertIn("time-series", reason)

    def test_real_factor_passes(self) -> None:
        from app.services.factor_audit_service import is_suspicious
        sus, _ = is_suspicious(self._make())
        self.assertFalse(sus)


class FactorAuditLibraryTests(unittest.IsolatedAsyncioTestCase):
    """Per-test temp DB so we don't pollute the shared trading_platform.db."""

    def setUp(self) -> None:
        self._tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self._tmp_dir.cleanup()

    async def asyncSetUp(self) -> None:
        db_path = Path(self._tmp_dir.name) / f"audit_{id(self)}.db"
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}", echo=False, future=True
        )
        sf = async_sessionmaker(engine, expire_on_commit=False)
        from app.services import factor_audit_service as svc
        self._patches = [patch.object(svc, "AsyncSessionLocal", sf)]
        for p in self._patches:
            p.start()
        from app.db.engine import Base
        from app.db import tables  # noqa: F401 — register ORM
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._engine = engine
        self._sf = sf

    async def asyncTearDown(self) -> None:
        for p in self._patches:
            p.stop()
        await self._engine.dispose()

    async def test_audit_marks_only_suspicious(self) -> None:
        from app.services import factor_audit_service as svc
        from app.db.tables import FactorRecord
        async with self._sf() as s:
            s.add(FactorRecord(
                formula="neg(close)", fitness=0.05, sharpe=4.7,
                ic_5d=0.04, max_drawdown=0.2,
            ))
            s.add(FactorRecord(
                formula="rank(decay_linear(ts_std(returns,20),5))",
                fitness=0.06, sharpe=1.2, ic_5d=0.05, max_drawdown=0.15,
            ))
            await s.commit()

        result = await svc.audit_library()
        self.assertEqual(result["scanned"], 2)
        self.assertEqual(result["newly_quarantined"], 1)
        self.assertEqual(result["total_quarantined"], 1)

        async with self._sf() as s:
            quar = (
                await s.execute(
                    select(FactorRecord).where(FactorRecord.quarantined == True)  # noqa: E712
                )
            ).scalars().all()
        self.assertEqual(len(quar), 1)
        self.assertEqual(quar[0].formula, "neg(close)")

    async def test_audit_idempotent(self) -> None:
        from app.services import factor_audit_service as svc
        from app.db.tables import FactorRecord
        async with self._sf() as s:
            s.add(FactorRecord(
                formula="neg(close)", fitness=0.05, sharpe=4.7,
                ic_5d=0.04, max_drawdown=0.2,
            ))
            await s.commit()

        first = await svc.audit_library()
        second = await svc.audit_library()
        self.assertEqual(first["newly_quarantined"], 1)
        self.assertEqual(second["newly_quarantined"], 0)
        self.assertEqual(second["total_quarantined"], 1)


if __name__ == "__main__":
    unittest.main()
