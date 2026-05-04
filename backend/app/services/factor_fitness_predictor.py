"""Cheap fitness predictor for Factor Forge GP search.

Trains a small gradient-boosted regressor (LightGBM if available, sklearn
GradientBoostingRegressor otherwise) over structural + bag-of-words
features extracted from a factor AST. Consumed by the GP loop *before* the
expensive backtest runs so we can prune low-IC candidates cheaply.

Features are deliberately simple - no time-series math is performed; the
model just learns "shapes of formulas that historically had high IC".
"""
from __future__ import annotations

import logging
import pickle  # nosec B403 - model cache, not user input
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.services import factor_vector_store
from core.factors.ast import FactorNode, depth as ast_depth, node_count

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature vocabulary (stable order - must match between train and predict)
# ---------------------------------------------------------------------------

_OPS_VOCAB: tuple[str, ...] = (
    "rank", "zscore", "min_max_scale", "industry_neutral", "market_cap_neutral",
    "ts_mean", "ts_std", "ts_min", "ts_max", "ts_sum", "ts_argmin", "ts_argmax",
    "ts_rank", "delta", "delay", "decay_linear", "ema", "sma",
    "correlation", "covariance", "regression_neutral",
    "add", "sub", "mul", "div", "neg", "abs", "sign", "log", "sqrt", "power",
    "if_else", "quantile",
)

_COL_VOCAB: tuple[str, ...] = (
    "close", "open", "high", "low", "volume", "returns", "vwap",
    "sector", "mcap", "news_sent", "news_count",
)

# [depth, node_count] + ops + cols + [int_args, float_args, mean_window]
FEATURE_DIM: int = 2 + len(_OPS_VOCAB) + len(_COL_VOCAB) + 3

_MIN_WINDOW_SIZE = 2

# Where the trained model is cached on disk. Tests can monkeypatch this.
_MODEL_PATH: Path = (
    Path(__file__).resolve().parents[2] / "data" / "factor_fitness_model.pkl"
)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def features_from_node(node: FactorNode) -> np.ndarray:
    """Extract a fixed-length feature vector from a factor AST.

    Layout (length ``FEATURE_DIM``)::

        [depth, node_count,
         *op_counts (len=_OPS_VOCAB),
         *col_counts (len=_COL_VOCAB),
         int_arg_count, float_arg_count, mean_window_size]
    """
    op_counts: dict[str, int] = {op: 0 for op in _OPS_VOCAB}
    col_counts: dict[str, int] = {c: 0 for c in _COL_VOCAB}
    int_args = 0
    float_args = 0
    windows: list[int] = []

    def visit(n: Any) -> None:
        nonlocal int_args, float_args
        if isinstance(n, FactorNode):
            if n.op in op_counts:
                op_counts[n.op] += 1
            for arg in n.args:
                visit(arg)
            return
        if isinstance(n, bool):
            # bool subclasses int; skip so it doesn't count as int arg
            return
        if isinstance(n, str):
            if n in col_counts:
                col_counts[n] += 1
            return
        if isinstance(n, int):
            int_args += 1
            if n >= _MIN_WINDOW_SIZE:
                windows.append(n)
            return
        if isinstance(n, float):
            float_args += 1
            return

    visit(node)

    feat: list[float] = [
        float(ast_depth(node)),
        float(node_count(node)),
    ]
    feat.extend(float(op_counts[op]) for op in _OPS_VOCAB)
    feat.extend(float(col_counts[c]) for c in _COL_VOCAB)
    feat.append(float(int_args))
    feat.append(float(float_args))
    feat.append(float(np.mean(windows)) if windows else 0.0)
    return np.asarray(feat, dtype=np.float32)


# ---------------------------------------------------------------------------
# Model selection (LightGBM preferred, sklearn fallback)
# ---------------------------------------------------------------------------


def _try_lightgbm() -> Optional[type]:
    """Return ``LGBMRegressor`` if importable, else ``None``."""
    try:
        from lightgbm import LGBMRegressor

        return LGBMRegressor
    except ImportError:
        return None


def _sklearn_fallback() -> Optional[type]:
    """Return ``GradientBoostingRegressor`` if importable, else ``None``."""
    try:
        from sklearn.ensemble import GradientBoostingRegressor

        return GradientBoostingRegressor
    except ImportError:
        return None


def _build_model() -> Optional[Any]:
    """Instantiate the best available regressor."""
    lgbm_cls = _try_lightgbm()
    if lgbm_cls is not None:
        return lgbm_cls(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=5,
            verbose=-1,
        )
    skl_cls = _sklearn_fallback()
    if skl_cls is not None:
        return skl_cls(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=5,
        )
    return None


# ---------------------------------------------------------------------------
# Predictor wrapper
# ---------------------------------------------------------------------------


class FitnessPredictor:
    """Wraps a fitted regressor; returns 0.0 when untrained or on failure."""

    def __init__(self, model: Optional[Any] = None) -> None:
        self._model = model

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def predict(self, node: FactorNode) -> float:
        if self._model is None:
            return 0.0
        feat = features_from_node(node).reshape(1, -1)
        try:
            return float(self._model.predict(feat)[0])
        except Exception:
            logger.warning("FitnessPredictor.predict failed", exc_info=True)
            return 0.0


# ---------------------------------------------------------------------------
# Training / loading
# ---------------------------------------------------------------------------


def _records_to_xy(
    records: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
    """Parse formulas, build X matrix and y target vector."""
    from core.factors.ast import parse as parse_ast

    feats: list[np.ndarray] = []
    targets: list[float] = []
    for r in records:
        formula = r.get("formula")
        if not formula:
            continue
        try:
            node = parse_ast(formula)
        except Exception:
            continue
        target = r.get("ic_5d")
        if target is None:
            target = r.get("fitness", 0.0)
        if target is None:
            continue
        feats.append(features_from_node(node))
        targets.append(float(target))
    if not feats:
        return (
            np.zeros((0, FEATURE_DIM), dtype=np.float32),
            np.zeros(0, dtype=np.float32),
        )
    return np.vstack(feats), np.asarray(targets, dtype=np.float32)


def _persist_model(model: Any) -> None:
    """Best-effort pickle of the fitted model to ``_MODEL_PATH``."""
    try:
        _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_MODEL_PATH, "wb") as f:
            pickle.dump(model, f)
    except Exception:
        logger.warning(
            "Failed to persist fitness model to %s", _MODEL_PATH, exc_info=True
        )


async def train_from_library(min_records: int = 30) -> FitnessPredictor:
    """Train a fitness predictor from existing factor records.

    Returns an untrained ``FitnessPredictor`` (predict -> 0.0) when there
    aren't enough usable records or no model backend is available.
    """
    records = await factor_vector_store.list_factors(limit=10_000)
    if len(records) < min_records:
        logger.info(
            "Skipping fitness-predictor training - only %d records (< %d)",
            len(records),
            min_records,
        )
        return FitnessPredictor()

    X, y = _records_to_xy(records)
    if X.shape[0] < min_records:
        logger.info(
            "After parsing, only %d valid records (< %d)", X.shape[0], min_records
        )
        return FitnessPredictor()

    model = _build_model()
    if model is None:
        logger.warning(
            "No regressor backend available (lightgbm/sklearn missing)"
        )
        return FitnessPredictor()

    try:
        model.fit(X, y)
    except Exception:
        logger.warning("Fitness model fit failed", exc_info=True)
        return FitnessPredictor()

    _persist_model(model)
    return FitnessPredictor(model)


def load_predictor() -> FitnessPredictor:
    """Load the on-disk model if present; return untrained predictor otherwise."""
    if not _MODEL_PATH.exists():
        return FitnessPredictor()
    try:
        with open(_MODEL_PATH, "rb") as f:
            model = pickle.load(f)  # nosec B301 - model cache controlled by us
        return FitnessPredictor(model)
    except Exception:
        logger.warning(
            "Failed to load fitness model from %s", _MODEL_PATH, exc_info=True
        )
        return FitnessPredictor()
