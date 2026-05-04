"""FAISS-backed vector library for surviving factors.

- Each factor is stored once.
- Two embeddings:
  * formula_embedding - OpenAI text-embedding-3-small of the formula string (1536 dims).
  * return_embedding  - z-scored 252-bar cumulative return vector (256 dims; truncate or zero-pad).
- Dedupe rejects new candidates whose cosine similarity to any existing
  factor exceeds the threshold (default 0.8) on EITHER embedding.

Note: implementation uses raw numpy cosine similarity rather than FAISS.
At <10k factors a DB scan is cheap and avoids a heavyweight binary
dependency. If perf becomes an issue we add FAISS later.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import numpy as np
from sqlalchemy import desc, select

from app import runtime_settings
from app.db.engine import AsyncSessionLocal
from app.db.tables import FactorRecord

logger = logging.getLogger(__name__)


_FORMULA_EMBED_DIM = 1536  # text-embedding-3-small
_RETURN_EMBED_DIM = 256


def _serialize_vec(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def _deserialize_vec(b: bytes, dim: int) -> np.ndarray:
    arr = np.frombuffer(b, dtype=np.float32)
    if arr.size != dim:
        return np.zeros(dim, dtype=np.float32)
    return arr


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n <= 0:
        return v
    return v / n


def embed_return_series(returns: np.ndarray, dim: int = _RETURN_EMBED_DIM) -> np.ndarray:
    """z-score then truncate/pad the per-bar return vector to fixed dim."""
    arr = np.asarray(returns, dtype=np.float32)
    if arr.size == 0:
        return np.zeros(dim, dtype=np.float32)
    mean = float(arr.mean())
    std = float(arr.std()) or 1.0
    z = (arr - mean) / std
    if z.size >= dim:
        return z[:dim].astype(np.float32)
    out = np.zeros(dim, dtype=np.float32)
    out[: z.size] = z
    return out


def _embed_formula_sync(text: str) -> np.ndarray:
    """OpenAI text-embedding-3-small of the formula string.

    Returns a zero vector when the SDK or API key is unavailable, so
    callers can still persist factors offline (dedupe will fall back to
    the return-series similarity).
    """
    try:
        from openai import OpenAI
    except ImportError:
        return np.zeros(_FORMULA_EMBED_DIM, dtype=np.float32)
    api_key = runtime_settings.get_setting("OPENAI_API_KEY", "") or ""
    if not api_key:
        return np.zeros(_FORMULA_EMBED_DIM, dtype=np.float32)
    try:
        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(model="text-embedding-3-small", input=text)
        return np.asarray(resp.data[0].embedding, dtype=np.float32)
    except Exception:
        logger.warning("formula embed failed for %r", text[:50], exc_info=True)
        return np.zeros(_FORMULA_EMBED_DIM, dtype=np.float32)


async def embed_formula(text: str) -> np.ndarray:
    return await asyncio.to_thread(_embed_formula_sync, text)


async def is_duplicate(
    formula: str,
    formula_emb: np.ndarray,
    return_emb: np.ndarray,
    threshold: float = 0.8,
) -> tuple[bool, int | None]:
    """Returns (is_dup, matching_record_id) - None if no match."""
    fe_norm = _normalize(np.asarray(formula_emb, dtype=np.float32))
    re_norm = _normalize(np.asarray(return_emb, dtype=np.float32))
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(FactorRecord))).scalars().all()
    for r in rows:
        if r.formula == formula:
            return True, r.id
        f_other = _normalize(_deserialize_vec(r.formula_embedding or b"", _FORMULA_EMBED_DIM))
        r_other = _normalize(_deserialize_vec(r.return_embedding or b"", _RETURN_EMBED_DIM))
        f_sim = float(np.dot(fe_norm, f_other))
        r_sim = float(np.dot(re_norm, r_other))
        if f_sim > threshold or r_sim > threshold:
            return True, r.id
    return False, None


async def add_factor(
    formula: str,
    *,
    fitness: float,
    ic_1d: float | None = None,
    ic_5d: float | None = None,
    ic_20d: float | None = None,
    icir: float | None = None,
    sharpe: float | None = None,
    max_drawdown: float | None = None,
    turnover: float | None = None,
    formula_embedding: np.ndarray | None = None,
    return_embedding: np.ndarray | None = None,
    metadata: dict[str, Any] | None = None,
    generation: int = 0,
    dedupe: bool = True,
    dedupe_threshold: float = 0.8,
    quarantined: bool = False,
    enforce_gate: bool = True,
    n_obs: int | None = None,
) -> int | None:
    """Insert a new factor record. Returns None when ``dedupe=True`` and
    a sufficiently similar factor already exists, OR when ``enforce_gate``
    is True and the candidate fails the multi-condition quality gate.

    Quality gate (CLEAN sub-plan, relaxed for real-world noise):
      |fitness| >= 0.04                           — IC magnitude meaningful
      |ic_5d|  > 0.025                            — sign-agnostic; long-only
                                                    factor with negative IC
                                                    is still tradable as short
      sharpe is not None and |sharpe| < 8         — block obvious leakage
                                                    (sharpe > 8 = look-ahead);
                                                    keep negative sharpes
      max_drawdown < 0.50                         — relaxed from 0.30: real
                                                    portfolios can hit 30-40%
      n_obs > 5000  (when supplied)
    Auto-quarantine (still persist, but flag) handled by factor_audit_service.
    """
    if enforce_gate:
        if abs(fitness) < 0.04:
            return None
        if ic_5d is None or abs(ic_5d) <= 0.025:
            return None
        if sharpe is None or abs(sharpe) >= 8.0:
            return None
        if max_drawdown is None or max_drawdown >= 0.50:
            return None
        if n_obs is not None and n_obs <= 5000:
            return None
    if len(formula) < 10:
        quarantined = True

    fe = (
        formula_embedding
        if formula_embedding is not None
        else await embed_formula(formula)
    )
    re_ = (
        return_embedding
        if return_embedding is not None
        else np.zeros(_RETURN_EMBED_DIM, dtype=np.float32)
    )
    if dedupe:
        is_dup, _match = await is_duplicate(
            formula, fe, re_, threshold=dedupe_threshold
        )
        if is_dup:
            return None

    async with AsyncSessionLocal() as session:
        row = FactorRecord(
            formula=formula,
            fitness=float(fitness),
            ic_1d=ic_1d,
            ic_5d=ic_5d,
            ic_20d=ic_20d,
            icir=icir,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            turnover=turnover,
            formula_embedding=_serialize_vec(fe),
            return_embedding=_serialize_vec(re_),
            metadata_json=json.dumps(metadata) if metadata else None,
            generation=int(generation),
            quarantined=bool(quarantined),
        )
        session.add(row)
        try:
            await session.commit()
            await session.refresh(row)
            return int(row.id)
        except Exception:
            await session.rollback()
            logger.warning("Factor insert failed for %r", formula[:80], exc_info=True)
            return None


async def list_factors(
    limit: int = 100,
    *,
    sort_by: str = "fitness",
    min_fitness: float | None = None,
    include_quarantined: bool = False,
) -> list[dict[str, Any]]:
    sort_col = getattr(FactorRecord, sort_by, FactorRecord.fitness)
    async with AsyncSessionLocal() as session:
        q = select(FactorRecord)
        if min_fitness is not None:
            q = q.where(FactorRecord.fitness >= min_fitness)
        if not include_quarantined:
            q = q.where(FactorRecord.quarantined == False)  # noqa: E712 — SQL boolean
        q = q.order_by(desc(sort_col)).limit(limit)
        rows = (await session.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "formula": r.formula,
            "fitness": r.fitness,
            "ic_1d": r.ic_1d,
            "ic_5d": r.ic_5d,
            "ic_20d": r.ic_20d,
            "icir": r.icir,
            "sharpe": r.sharpe,
            "max_drawdown": r.max_drawdown,
            "turnover": r.turnover,
            "generation": r.generation,
            "quarantined": r.quarantined,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
