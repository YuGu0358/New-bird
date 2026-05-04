"""AI candidate-pool scoring and persistence."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import CandidatePoolItem
from app.services import openai_service, tavily_service
from app.services.monitoring.symbols import _normalize_symbols
from app.services.monitoring.trends import _empty_trend_snapshot, fetch_trend_snapshots

TECH_CANDIDATE_SYMBOLS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "AVGO",
    "AMD",
    "ADBE",
    "CRM",
    "ORCL",
    "NOW",
    "SNOW",
    "PANW",
    "CRWD",
    "PLTR",
    "MDB",
    "QCOM",
    "INTU",
    "SMCI",
]

ETF_CANDIDATE_SYMBOLS = [
    "QQQ",
    "SPY",
    "VOO",
    "IVV",
    "VTI",
    "XLK",
    "VGT",
    "SMH",
    "SOXX",
    "IGV",
    "DIA",
    "IWM",
]

MAX_CANDIDATES = 5


def _score_candidate(trend: dict[str, Any]) -> float | None:
    day = trend.get("day_change_percent")
    week = trend.get("week_change_percent")
    month = trend.get("month_change_percent")

    if not isinstance(day, (int, float)) or not isinstance(week, (int, float)) or not isinstance(month, (int, float)):
        return None

    score = (day * 0.2) + (week * 0.35) + (month * 0.45)
    return round(score, 4)


def _fallback_candidate_reason(symbol: str, trend: dict[str, Any]) -> str:
    week = trend.get("week_change_percent")
    month = trend.get("month_change_percent")
    week_text = f"近一周 {week:.2f}%" if isinstance(week, (int, float)) else "近一周数据缺失"
    month_text = f"近一月 {month:.2f}%" if isinstance(month, (int, float)) else "近一月数据缺失"
    return f"{symbol} 在科技/ETF 候选池中动量靠前，{week_text}，{month_text}。"


def _compress_reason(summary: str, fallback: str) -> str:
    compact_summary = " ".join(summary.split())
    if not compact_summary:
        return fallback
    if len(compact_summary) <= 180:
        return compact_summary
    return f"{compact_summary[:177].rstrip()}..."


async def _build_candidate_reasons(
    picked: Sequence[dict[str, Any]],
) -> dict[str, str]:
    async def _load_reason(item: dict[str, Any]) -> tuple[str, str]:
        symbol = str(item["symbol"])
        fallback_reason = _fallback_candidate_reason(symbol, item["trend"])

        try:
            response = await tavily_service.fetch_news_summary(symbol)
            summary = str(response.get("summary", "")).strip()
        except Exception:
            summary = ""

        return symbol, _compress_reason(summary, fallback_reason)

    responses = await asyncio.gather(*[_load_reason(item) for item in picked], return_exceptions=False)
    return {symbol: reason for symbol, reason in responses}


def _pick_top_candidates(scored_items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_items = sorted(
        scored_items,
        key=lambda item: (float(item["score"]), float(item["trend"].get("month_change_percent") or 0.0)),
        reverse=True,
    )

    tech_items = [item for item in sorted_items if item["category"] == "科技股"]
    etf_items = [item for item in sorted_items if item["category"] == "ETF"]

    picked: list[dict[str, Any]] = []
    picked.extend(tech_items[:3])
    picked.extend(etf_items[:2])

    picked_symbols = {item["symbol"] for item in picked}
    for item in sorted_items:
        if len(picked) >= MAX_CANDIDATES:
            break
        if item["symbol"] in picked_symbols:
            continue
        picked.append(item)
        picked_symbols.add(item["symbol"])

    return picked[:MAX_CANDIDATES]


async def _load_cached_candidate_pool(
    session: AsyncSession,
    snapshot_date: str,
) -> list[CandidatePoolItem]:
    result = await session.execute(
        select(CandidatePoolItem)
        .where(CandidatePoolItem.snapshot_date == snapshot_date)
        .order_by(CandidatePoolItem.rank, CandidatePoolItem.symbol)
    )
    return result.scalars().all()


async def build_candidate_pool(
    session: AsyncSession,
    *,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Create or load today's top-5 candidate pool."""

    snapshot_date = datetime.now(timezone.utc).date().isoformat()

    if not force_refresh:
        cached_rows = await _load_cached_candidate_pool(session, snapshot_date)
        if cached_rows:
            trend_map = await fetch_trend_snapshots([row.symbol for row in cached_rows])
            now = datetime.now(timezone.utc)
            return [
                {
                    "symbol": row.symbol,
                    "rank": row.rank,
                    "category": row.category,
                    "score": row.score,
                    "reason": row.reason,
                    "trend": trend_map.get(row.symbol, _empty_trend_snapshot(row.symbol, now)),
                }
                for row in cached_rows
            ]

    candidate_symbols = _normalize_symbols(TECH_CANDIDATE_SYMBOLS + ETF_CANDIDATE_SYMBOLS)
    trend_map = await fetch_trend_snapshots(candidate_symbols, force_refresh=True)

    scored_items: list[dict[str, Any]] = []
    for symbol in candidate_symbols:
        trend = trend_map.get(symbol)
        if trend is None:
            continue
        score = _score_candidate(trend)
        if score is None:
            continue
        scored_items.append(
            {
                "symbol": symbol,
                "category": "ETF" if symbol in ETF_CANDIDATE_SYMBOLS else "科技股",
                "score": score,
                "trend": trend,
            }
        )

    deterministic_picks = _pick_top_candidates(scored_items)
    shortlist = sorted(
        scored_items,
        key=lambda item: float(item["score"]),
        reverse=True,
    )[:8]

    picked = deterministic_picks
    if openai_service.is_configured() and shortlist:
        try:
            ai_ranked = await openai_service.rank_candidates(shortlist)
            if len(ai_ranked) >= MAX_CANDIDATES:
                picked = ai_ranked
        except Exception:
            picked = deterministic_picks

    needs_reason_refresh = any(not item.get("reason") for item in picked)
    if needs_reason_refresh:
        reasons = await _build_candidate_reasons(picked)
    else:
        reasons = {str(item["symbol"]).upper(): str(item.get("reason", "")).strip() for item in picked}

    await session.execute(delete(CandidatePoolItem).where(CandidatePoolItem.snapshot_date == snapshot_date))
    for index, item in enumerate(picked, start=1):
        session.add(
            CandidatePoolItem(
                snapshot_date=snapshot_date,
                symbol=item["symbol"],
                rank=index,
                category=item["category"],
                score=float(item["score"]),
                reason=reasons.get(item["symbol"], _fallback_candidate_reason(item["symbol"], item["trend"])),
            )
        )

    await session.commit()

    return [
        {
            "symbol": item["symbol"],
            "rank": index,
            "category": item["category"],
            "score": float(item["score"]),
            "reason": reasons.get(item["symbol"], _fallback_candidate_reason(item["symbol"], item["trend"])),
            "trend": item["trend"],
        }
        for index, item in enumerate(picked, start=1)
    ]
