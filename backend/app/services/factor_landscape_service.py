"""PCA-2D projection of factor formula embeddings for the landscape view."""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sqlalchemy import desc, select

from app.db.engine import AsyncSessionLocal
from app.db.tables import FactorRecord

logger = logging.getLogger(__name__)

# text-embedding-3-small produces 1536-dim vectors; matches factor_vector_store.
FORMULA_EMBEDDING_DIM = 1536


def _deserialize_vec(b: bytes | None, dim: int) -> np.ndarray | None:
    """Same encoding as factor_vector_store.py — float32 raw bytes."""
    if not b:
        return None
    arr = np.frombuffer(b, dtype=np.float32)
    if arr.size != dim:
        return None
    return arr.copy()


def _pca_2d(matrix: np.ndarray) -> np.ndarray:
    """Cheap 2-component PCA via SVD; standard-scaled inputs.

    Returns shape (n, 2). NaN-safe — replaces nan/inf with 0 first.
    """
    X = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
    X = X - X.mean(axis=0, keepdims=True)
    # SVD: X = U S Vt; first 2 PCs = X @ Vt[:2].T
    try:
        _, _, Vt = np.linalg.svd(X, full_matrices=False)
    except np.linalg.LinAlgError:
        return np.zeros((X.shape[0], 2), dtype=np.float32)
    components = Vt[:2]
    return (X @ components.T).astype(np.float32)


async def compute_landscape(limit: int = 500) -> list[dict[str, Any]]:
    """Project factor embeddings to 2D + return per-factor coords + metadata."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorRecord)
                .order_by(desc(FactorRecord.fitness))
                .limit(limit)
            )
        ).scalars().all()
    if not rows:
        return []
    valid: list[tuple[FactorRecord, np.ndarray]] = []
    for r in rows:
        vec = _deserialize_vec(r.formula_embedding, FORMULA_EMBEDDING_DIM)
        if vec is None or np.allclose(vec, 0):
            continue
        valid.append((r, vec))
    if not valid:
        return []
    matrix = np.vstack([v for _, v in valid])
    if matrix.shape[0] < 2:
        # PCA needs >=2 points; fall back to (0, 0) for the single point.
        coords = np.zeros((1, 2), dtype=np.float32)
    else:
        coords = _pca_2d(matrix)
    return [
        {
            "id": r.id,
            "formula": r.formula,
            "fitness": float(r.fitness),
            "ic_5d": float(r.ic_5d) if r.ic_5d is not None else None,
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
        }
        for i, (r, _) in enumerate(valid)
    ]
