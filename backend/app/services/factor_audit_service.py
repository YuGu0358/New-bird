"""Audit existing factor library for suspicious entries.

Heuristics that flag a factor as quarantined:
- sharpe > 3.0 OR sharpe < -3.0 — statistical impossibility on real OHLCV
- abs(ic_5d) >= 0.95 — perfectly fitted = leakage
- max_drawdown is None or > 0.50 — never validated or way too risky
- formula length < 10 — too trivial (e.g. neg(close), rank(volume))
- formula has NO time-series operator — purely cross-sectional / element-wise
  factors are by definition memorising today's snapshot, not predictive
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.db.engine import AsyncSessionLocal
from app.db.tables import FactorRecord

logger = logging.getLogger(__name__)


_TIME_SERIES_OPS = {
    "ts_mean", "ts_std", "ts_min", "ts_max", "ts_sum", "ts_argmin",
    "ts_argmax", "ts_rank", "delta", "delay", "decay_linear",
    "correlation", "covariance", "regression_neutral", "ema", "sma",
}


def is_suspicious(record: FactorRecord) -> tuple[bool, str | None]:
    """Returns (is_suspicious, reason). Pure function on a record."""
    formula = record.formula or ""
    if record.sharpe is not None and (record.sharpe > 3.0 or record.sharpe < -3.0):
        return True, f"sharpe out of plausible range ({record.sharpe:.2f})"
    if record.ic_5d is not None and abs(record.ic_5d) >= 0.95:
        return True, f"ic_5d near-perfect ({record.ic_5d:.2f}) — likely leakage"
    if record.max_drawdown is None or record.max_drawdown > 0.50:
        return True, "max_drawdown missing or excessive"
    if len(formula) < 10:
        return True, f"formula trivially short ({len(formula)} chars)"
    if not any(op in formula for op in _TIME_SERIES_OPS):
        return True, "no time-series operator (cross-sectional only)"
    return False, None


async def audit_library() -> dict:
    """Scan factor_records, mark suspicious as quarantined.

    Returns counts: { scanned, newly_quarantined, total_quarantined }
    """
    newly = 0
    total_quarantined = 0
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(FactorRecord))).scalars().all()
        for r in rows:
            sus, reason = is_suspicious(r)
            if sus and not r.quarantined:
                r.quarantined = True
                newly += 1
                logger.info("Quarantined factor #%d: %s", r.id, reason)
            if r.quarantined:
                total_quarantined += 1
        await session.commit()
    return {
        "scanned": len(rows),
        "newly_quarantined": newly,
        "total_quarantined": total_quarantined,
    }
