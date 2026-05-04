"""Compute ensemble factor scores across the active universe.

Pulls all non-quarantined factors with fitness >= 0.04, evaluates each on
the symbol panel, ranks per-day cross-sectionally, then weights by fitness
and aggregates into one ensemble_rank per symbol per day.

Returns a DataFrame with columns:
  ensemble_rank: float in [0, 1]
  contributing_factors: list of {factor_id, formula, fitness, rank_value}
  factor_disagreement: float — std of factor ranks (used for confidence)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.services import factor_data_service, factor_vector_store
from core.factors.ast import parse
from core.factors.eval import evaluate

logger = logging.getLogger(__name__)


_MIN_FITNESS = 0.04
_DEFAULT_TOP_FACTORS = 20
_DEFAULT_LOOKBACK_DAYS = 60
_MAX_LIBRARY_SCAN = 1000


async def compute_ensemble_score(
    symbols: list[str],
    target_date: date,
    *,
    top_n_factors: int = _DEFAULT_TOP_FACTORS,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Compute the ensemble rank for each symbol on ``target_date``.

    Returns DataFrame indexed by symbol with columns:
      - ensemble_rank: float in [0, 1]
      - contributing_factors: list[dict] (top-3 by per-symbol contribution)
      - factor_disagreement: float — cross-factor std on this symbol

    Returns an empty DataFrame when the library is empty, the panel cannot
    be loaded, or no factor evaluates successfully.
    """
    factors = await factor_vector_store.list_factors(
        limit=_MAX_LIBRARY_SCAN,
        sort_by="fitness",
        min_fitness=_MIN_FITNESS,
        include_quarantined=False,
    )
    if not factors:
        logger.info("ensemble: no usable factors in library")
        return pd.DataFrame(
            columns=["ensemble_rank", "contributing_factors", "factor_disagreement"]
        )
    factors = factors[:top_n_factors]

    # Buffer for warmup of rolling/lagging operators inside the AST.
    start = target_date - timedelta(days=lookback_days * 2 + 30)
    panel = await factor_data_service.get_panel(start, target_date, symbols=symbols)
    if panel.empty:
        return pd.DataFrame(
            columns=["ensemble_rank", "contributing_factors", "factor_disagreement"]
        )

    panel = _augment_panel(panel)

    weights = np.array([float(f.get("fitness", 0)) for f in factors], dtype=np.float64)
    weights = weights / max(weights.sum(), 1e-9)

    last_date = panel.index.get_level_values("date").max()
    rank_matrix: list[pd.Series] = []
    contributing: list[dict] = []

    for f, w in zip(factors, weights):
        try:
            node = parse(f["formula"])
            scored = evaluate(node, panel)
            if not isinstance(scored, pd.Series):
                continue
            try:
                on_date = scored.xs(last_date, level="date")
            except KeyError:
                continue
            if on_date.empty:
                continue
            ranked = on_date.rank(pct=True)  # cross-sectional 0..1
            rank_matrix.append(ranked)
            contributing.append(
                {
                    "factor_id": f.get("id"),
                    "formula": f.get("formula"),
                    "fitness": f.get("fitness"),
                    "weight": float(w),
                }
            )
        except Exception:
            logger.debug(
                "eval failed for factor %s",
                str(f.get("formula", ""))[:60],
                exc_info=True,
            )
            continue

    if not rank_matrix:
        return pd.DataFrame(
            columns=["ensemble_rank", "contributing_factors", "factor_disagreement"]
        )

    df = pd.concat(rank_matrix, axis=1)
    df.columns = [c["factor_id"] for c in contributing]

    # Re-normalise weights across the factors that actually evaluated.
    used_weights = np.array([c["weight"] for c in contributing], dtype=np.float64)
    used_weights = used_weights / max(used_weights.sum(), 1e-9)

    ensemble = (df * used_weights).sum(axis=1)
    disagreement = df.std(axis=1).fillna(0.0)

    out = pd.DataFrame(
        {
            "ensemble_rank": ensemble,
            "factor_disagreement": disagreement,
        }
    )

    contributions: list[list[dict]] = []
    for sym in df.index:
        row = df.loc[sym]
        per_factor = []
        for i, c in enumerate(contributing):
            val = row.iloc[i]
            per_factor.append(
                {
                    **c,
                    "rank_value": float(val) if pd.notna(val) else None,
                }
            )
        per_factor.sort(key=lambda x: x.get("rank_value") or 0.0, reverse=True)
        contributions.append(per_factor[:3])
    out["contributing_factors"] = contributions
    return out


def _augment_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Add panel-derived columns the AST evaluator may reference.

    Returns a copy; never mutates the caller's frame.
    """
    out = panel.copy()
    if "returns" not in out.columns:
        out["returns"] = out.groupby(level="symbol")["close"].pct_change()
    if "vwap" not in out.columns:
        out["vwap"] = out["close"]  # fallback when bars omit vwap
    # Stub columns the evaluator may reference but we don't actually need.
    if "sector" not in out.columns:
        out["sector"] = 0.0
    if "mcap" not in out.columns:
        out["mcap"] = 1.0
    if "news_sent" not in out.columns:
        out["news_sent"] = 0.0
    if "news_count" not in out.columns:
        out["news_count"] = 0.0
    return out
