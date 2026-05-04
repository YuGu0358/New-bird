"""Generate today's trade recommendations from the multi-factor ensemble.

Produces a list of dicts with action / entry_zone / stop / target / holding
days / position_pct / confidence / reasoning / risk_signals. Persists into
the ``daily_recommendations`` table (wipe + rewrite per day) and exposes a
read helper for the API.
"""
from __future__ import annotations

import json
import logging
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, select

from app.db.engine import AsyncSessionLocal
from app.db.tables import DailyActiveUniverse, DailyRecommendation
from app.services import factor_data_service, multi_factor_score_service
from core.indicators import compute_indicator

logger = logging.getLogger(__name__)


# ---- Tuning constants ------------------------------------------------------

_HOLDING_DAYS = 5
_MAX_POSITION_PCT = 5.0       # single-name cap
_MAX_TOTAL_GROSS = 80.0       # sum of |position_pct| across all picks
_RSI_OVERBOUGHT = 70.0
_RSI_OVERSOLD = 30.0
_DEFAULT_ATR_PCT = 0.02       # 2% fallback when history is too short
_DEFAULT_TOP_K = 5
_PANEL_LOOKBACK_DAYS = 60
_DISAGREEMENT_RISK_THRESHOLD = 0.30
_RISK_CONFIDENCE_DECAY = 0.85
_VOL_RATIO_HIGH = 3.0
_VOL_RATIO_LOW = 0.3
_DISAGREEMENT_CONFIDENCE_CAP = 0.4


# ---- Risk metrics ----------------------------------------------------------


def _atr_pct(panel: pd.DataFrame, symbol: str, period: int = 14) -> float | None:
    """Average True Range / last close. ``None`` when history is insufficient."""
    try:
        sub = panel.xs(symbol, level="symbol").sort_index().tail(period + 1)
    except KeyError:
        return None
    if len(sub) < period + 1:
        return None
    high = sub["high"].astype(float)
    low = sub["low"].astype(float)
    close = sub["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    last_close = float(close.iloc[-1])
    if last_close <= 0 or pd.isna(atr):
        return None
    return float(atr) / last_close


def _rsi_last(panel: pd.DataFrame, symbol: str, period: int = 14) -> float | None:
    try:
        closes = (
            panel.xs(symbol, level="symbol")
            .sort_index()["close"]
            .astype(float)
            .tolist()
        )
    except KeyError:
        return None
    if len(closes) < period + 1:
        return None
    series = compute_indicator("rsi", closes, params={"period": period}).get("value") or []
    if not series or series[-1] is None:
        return None
    return float(series[-1])


def _volume_ratio(panel: pd.DataFrame, symbol: str, baseline_days: int = 20) -> float | None:
    """Today's volume relative to the prior 20-day average."""
    try:
        vols = (
            panel.xs(symbol, level="symbol")
            .sort_index()["volume"]
            .astype(float)
            .tail(baseline_days + 1)
        )
    except KeyError:
        return None
    if len(vols) < baseline_days + 1:
        return None
    today = float(vols.iloc[-1])
    baseline = float(vols.iloc[:-1].mean())
    if baseline <= 0:
        return None
    return today / baseline


# ---- Recommendation construction ------------------------------------------


def _build_recommendation(
    *,
    rank: int,
    symbol: str,
    action: str,
    last_close: float,
    atr_pct: float,
    ensemble_score: float,
    contributing: list[dict[str, Any]],
    disagreement: float,
    rsi: float | None,
    vol_ratio: float | None,
    target_position_pct: float,
) -> dict[str, Any]:
    """Compose a single recommendation dict using ATR-based bands.

    Long ("buy"): stop_loss < entry_low <= entry_high < take_profit.
    Short ("sell"): take_profit < entry_low <= entry_high < stop_loss.
    """
    if action == "buy":
        entry_low = last_close * (1 - 0.3 * atr_pct)
        entry_high = last_close * (1 + 0.3 * atr_pct)
        stop_loss = last_close * (1 - 1.5 * atr_pct)
        take_profit = last_close * (1 + 2.5 * atr_pct)
    else:
        entry_low = last_close * (1 - 0.3 * atr_pct)
        entry_high = last_close * (1 + 0.3 * atr_pct)
        stop_loss = last_close * (1 + 1.5 * atr_pct)
        take_profit = last_close * (1 - 2.5 * atr_pct)

    # Confidence: low disagreement + strong ensemble extreme.
    edge = abs(ensemble_score - 0.5) * 2  # 0..1
    disagreement_factor = 1.0 - min(disagreement, _DISAGREEMENT_CONFIDENCE_CAP) / _DISAGREEMENT_CONFIDENCE_CAP
    confidence = max(0.0, min(1.0, edge * disagreement_factor))

    risk_signals: list[dict[str, Any]] = []
    if action == "buy" and rsi is not None and rsi > _RSI_OVERBOUGHT:
        risk_signals.append(
            {
                "kind": "rsi_overbought",
                "value": round(rsi, 1),
                "message": f"RSI {rsi:.1f} > {_RSI_OVERBOUGHT:.0f}, 短期超买",
            }
        )
    if action == "sell" and rsi is not None and rsi < _RSI_OVERSOLD:
        risk_signals.append(
            {
                "kind": "rsi_oversold",
                "value": round(rsi, 1),
                "message": f"RSI {rsi:.1f} < {_RSI_OVERSOLD:.0f}, 短期超卖",
            }
        )
    if vol_ratio is not None and (vol_ratio > _VOL_RATIO_HIGH or vol_ratio < _VOL_RATIO_LOW):
        risk_signals.append(
            {
                "kind": "volume_anomaly",
                "value": round(vol_ratio, 2),
                "message": f"今日成交量为 20 日均的 {vol_ratio:.2f}x",
            }
        )
    if disagreement > _DISAGREEMENT_RISK_THRESHOLD:
        risk_signals.append(
            {
                "kind": "factor_disagreement",
                "value": round(disagreement, 3),
                "message": f"因子分歧大 (std={disagreement:.3f})",
            }
        )

    reasoning: list[dict[str, Any]] = []
    for c in (contributing or [])[:3]:
        rv = c.get("rank_value")
        interpretation = (
            "看多" if (rv is not None and rv > 0.5) else "看空"
        )
        reasoning.append(
            {
                "factor_id": c.get("factor_id"),
                "formula": (c.get("formula") or "")[:120],
                "fitness": c.get("fitness"),
                "weight": c.get("weight"),
                "interpretation": f"{interpretation} (rank={rv})",
            }
        )

    # Confidence-discount risk: each red signal cuts confidence 15%.
    if risk_signals:
        confidence = confidence * (_RISK_CONFIDENCE_DECAY ** len(risk_signals))

    return {
        "rank": rank,
        "symbol": symbol,
        "action": action,
        "entry_low": round(entry_low, 2),
        "entry_high": round(entry_high, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "holding_days": _HOLDING_DAYS,
        "position_pct": round(target_position_pct, 2),
        "confidence": round(confidence, 3),
        "ensemble_score": round(float(ensemble_score), 4),
        "reasoning": reasoning,
        "risk_signals": risk_signals,
    }


# ---- Top-level orchestration ----------------------------------------------


async def _resolve_universe(today: date_cls) -> tuple[list[str], date_cls]:
    """Return (universe, effective_date), falling back to the most recent date with a universe."""
    universe = await factor_data_service.get_active_universe(today, top_n=100)
    if universe:
        return universe, today
    async with AsyncSessionLocal() as session:
        most_recent = (
            await session.execute(
                select(func.max(DailyActiveUniverse.date)).where(
                    DailyActiveUniverse.date <= today
                )
            )
        ).scalar()
    if most_recent is None:
        return [], today
    universe = await factor_data_service.get_active_universe(most_recent, top_n=100)
    return universe, most_recent


async def generate_today_recommendations(
    target_date: date_cls | None = None,
    *,
    top_k_buy: int = _DEFAULT_TOP_K,
    top_k_sell: int = _DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Compute, persist, and return today's recommendations."""
    today = target_date or datetime.now(timezone.utc).date()
    universe, today = await _resolve_universe(today)
    if not universe:
        logger.warning("today_recommendations: no active universe")
        return []

    score_df = await multi_factor_score_service.compute_ensemble_score(universe, today)
    if score_df.empty:
        logger.info("today_recommendations: empty ensemble")
        return []
    score_df = score_df.dropna(subset=["ensemble_rank"])
    if score_df.empty:
        return []

    # Load panel for risk-signal computation (RSI / ATR / volume).
    start = today - timedelta(days=_PANEL_LOOKBACK_DAYS)
    panel = await factor_data_service.get_panel(start, today, symbols=universe)
    if panel.empty:
        logger.warning("today_recommendations: panel empty for %s", today)
        return []

    last_close_per_symbol = panel.groupby(level="symbol")["close"].last()

    sorted_buy = score_df.sort_values("ensemble_rank", ascending=False).head(top_k_buy)
    sorted_sell = score_df.sort_values("ensemble_rank").head(top_k_sell)

    n_total = len(sorted_buy) + len(sorted_sell)
    if n_total == 0:
        return []
    base_pct = min(_MAX_POSITION_PCT, _MAX_TOTAL_GROSS / max(n_total, 1))

    recs: list[dict[str, Any]] = []
    recs.extend(
        _build_side_recs(
            sorted_buy,
            action="buy",
            panel=panel,
            last_close_per_symbol=last_close_per_symbol,
            base_pct=base_pct,
        )
    )
    recs.extend(
        _build_side_recs(
            sorted_sell,
            action="sell",
            panel=panel,
            last_close_per_symbol=last_close_per_symbol,
            base_pct=base_pct,
        )
    )

    await _persist_recommendations(today, recs)
    return recs


def _build_side_recs(
    sorted_df: pd.DataFrame,
    *,
    action: str,
    panel: pd.DataFrame,
    last_close_per_symbol: pd.Series,
    base_pct: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r, (sym, row) in enumerate(sorted_df.iterrows(), start=1):
        if sym not in last_close_per_symbol.index:
            continue
        last = float(last_close_per_symbol[sym])
        if last <= 0:
            continue
        atr = _atr_pct(panel, sym) or _DEFAULT_ATR_PCT
        rsi = _rsi_last(panel, sym)
        vol = _volume_ratio(panel, sym)
        out.append(
            _build_recommendation(
                rank=r,
                symbol=sym,
                action=action,
                last_close=last,
                atr_pct=atr,
                ensemble_score=float(row["ensemble_rank"]),
                contributing=row["contributing_factors"],
                disagreement=float(row["factor_disagreement"]),
                rsi=rsi,
                vol_ratio=vol,
                target_position_pct=base_pct,
            )
        )
    return out


async def _persist_recommendations(
    target_date: date_cls, recs: list[dict[str, Any]]
) -> None:
    """Wipe + rewrite the rows for ``target_date``."""
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DailyRecommendation).where(DailyRecommendation.date == target_date)
        )
        for rec in recs:
            session.add(
                DailyRecommendation(
                    date=target_date,
                    symbol=rec["symbol"],
                    action=rec["action"],
                    entry_low=rec["entry_low"],
                    entry_high=rec["entry_high"],
                    stop_loss=rec["stop_loss"],
                    take_profit=rec["take_profit"],
                    holding_days=rec["holding_days"],
                    position_pct=rec["position_pct"],
                    confidence=rec["confidence"],
                    ensemble_score=rec["ensemble_score"],
                    reasoning_json=json.dumps(rec["reasoning"], ensure_ascii=False),
                    risk_signals_json=json.dumps(
                        rec["risk_signals"], ensure_ascii=False
                    ),
                    rank=rec["rank"],
                )
            )
        await session.commit()


async def get_today_recommendations(
    target_date: date_cls | None = None,
) -> list[dict[str, Any]]:
    """Read persisted recommendations for ``target_date`` (default UTC today)."""
    today = target_date or datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyRecommendation)
                .where(DailyRecommendation.date == today)
                .order_by(
                    DailyRecommendation.action.desc(), DailyRecommendation.rank
                )
            )
        ).scalars().all()
    return [
        {
            "date": r.date.isoformat(),
            "symbol": r.symbol,
            "action": r.action,
            "entry_low": r.entry_low,
            "entry_high": r.entry_high,
            "stop_loss": r.stop_loss,
            "take_profit": r.take_profit,
            "holding_days": r.holding_days,
            "position_pct": r.position_pct,
            "confidence": r.confidence,
            "ensemble_score": r.ensemble_score,
            "reasoning": json.loads(r.reasoning_json or "[]"),
            "risk_signals": json.loads(r.risk_signals_json or "[]"),
            "rank": r.rank,
        }
        for r in rows
    ]
