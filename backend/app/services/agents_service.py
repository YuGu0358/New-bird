"""Concrete glue between the agents framework and our data services.

Owns:
- LiveContextBuilder — pulls price, fundamentals, news, social signal,
  position from existing services.
- analyze(), council(), list_history() — public surface for the router.
- Persistence into AgentAnalysis.

Stays slim by delegating heavy lifting to core/agents/*.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AgentAnalysis
from app.services import (
    alpaca_service,
    chart_service,
    company_profile_service,
    market_research_service,
    polygon_service,
    social_signal_service,
)
from core.agents import (
    AnalysisContext,
    Analyzer,
    ContextBuilder,
    NewsItem,
    OpenAILLMRouter,
    PersonaResponse,
    PositionSnapshot,
    PriceSnapshot,
    SocialSignalSnapshot,
    get_persona,
    list_personas,
)
from core.i18n import DEFAULT_LANG, normalize_lang

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live context builder
# ---------------------------------------------------------------------------


class LiveContextBuilder(ContextBuilder):
    """Production ContextBuilder — reads from real services.

    Each source is wrapped in a try/except so a flaky external API never
    blocks the analysis. Missing pieces become None / empty in the
    AnalysisContext, and the LLM is told there is no data for that channel.
    """

    async def build(self, symbol: str, *, question: Optional[str] = None) -> AnalysisContext:
        symbol = symbol.upper()
        price = await self._build_price(symbol)
        fundamentals = await self._build_fundamentals(symbol)
        recent_news = await self._build_news(symbol)
        social = await self._build_social(symbol)
        position = await self._build_position(symbol)

        return AnalysisContext(
            symbol=symbol,
            question=question,
            price=price,
            fundamentals=fundamentals,
            recent_news=recent_news,
            social=social,
            position=position,
            generated_at=datetime.now(timezone.utc),
        )

    async def _build_price(self, symbol: str) -> PriceSnapshot:
        last = 0.0
        previous_close = 0.0
        try:
            previous_close = float(await polygon_service.get_previous_close(symbol))
        except Exception as exc:
            logger.debug("polygon previous close failed for %s: %s", symbol, exc)

        chart_points: list[dict[str, Any]] = []
        try:
            chart = await chart_service.get_symbol_chart(symbol, range_name="3mo")
            chart_points = list((chart or {}).get("points") or [])
        except Exception as exc:
            logger.debug("chart failed for %s: %s", symbol, exc)

        if chart_points:
            last = float(chart_points[-1].get("close") or chart_points[-1].get("price") or 0.0)
        if last == 0.0 and previous_close > 0.0:
            last = previous_close

        change_pct = self._pct(last, previous_close)
        week = self._lookback_pct(chart_points, 5)
        month = self._lookback_pct(chart_points, 22)
        year = self._lookback_pct(chart_points, 252)

        return PriceSnapshot(
            last=last,
            previous_close=previous_close or last,
            change_pct=change_pct,
            week_change_pct=week,
            month_change_pct=month,
            year_change_pct=year,
        )

    async def _build_fundamentals(self, symbol: str) -> dict[str, object]:
        try:
            profile = await company_profile_service.get_company_profile(symbol)
            if profile is None:
                return {}
            if hasattr(profile, "model_dump"):
                profile = profile.model_dump()
            return {
                "company_name": profile.get("company_name") or profile.get("name"),
                "sector": profile.get("sector"),
                "industry": profile.get("industry"),
                "summary": profile.get("business_summary") or profile.get("summary"),
                "market_cap": profile.get("market_cap"),
                "pe_ratio": profile.get("pe_ratio"),
            }
        except Exception as exc:
            logger.debug("fundamentals failed for %s: %s", symbol, exc)
            return {}

    async def _build_news(self, symbol: str) -> list[NewsItem]:
        try:
            payload = await market_research_service.get_news(symbol)
        except Exception as exc:
            logger.debug("news failed for %s: %s", symbol, exc)
            return []
        if payload is None:
            return []
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        items_raw = payload.get("items") or []
        if not items_raw and payload.get("summary"):
            items_raw = [{
                "title": payload.get("title") or symbol,
                "summary": payload.get("summary"),
                "source": payload.get("source") or "Tavily",
                "at": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            }]
        result: list[NewsItem] = []
        for item in items_raw[:5]:
            try:
                at_value = item.get("at") or item.get("timestamp") or datetime.now(timezone.utc).isoformat()
                if isinstance(at_value, str):
                    at = datetime.fromisoformat(at_value.replace("Z", "+00:00"))
                else:
                    at = at_value
                result.append(NewsItem(
                    title=str(item.get("title") or "")[:200],
                    summary=str(item.get("summary") or item.get("content") or "")[:500],
                    source=str(item.get("source") or "Tavily"),
                    at=at if at.tzinfo else at.replace(tzinfo=timezone.utc),
                ))
            except Exception as exc:
                logger.debug("news item parse failed: %s", exc)
        return result

    async def _build_social(self, symbol: str) -> Optional[SocialSignalSnapshot]:
        try:
            snapshot = await social_signal_service.score_symbol_signal(symbol)
        except Exception as exc:
            logger.debug("social signal failed for %s: %s", symbol, exc)
            return None
        if snapshot is None:
            return None
        if hasattr(snapshot, "model_dump"):
            snapshot = snapshot.model_dump()
        try:
            return SocialSignalSnapshot(
                social_score=float(snapshot.get("social_score") or 0.0),
                market_score=float(snapshot.get("market_score") or 0.0),
                final_weight=float(snapshot.get("final_weight") or 0.0),
                action=str(snapshot.get("action") or "hold"),
                confidence_label=str(snapshot.get("confidence_label") or "low"),
                reasons=list(snapshot.get("reasons") or [])[:5],
            )
        except (TypeError, ValueError):
            return None

    async def _build_position(self, symbol: str) -> Optional[PositionSnapshot]:
        try:
            positions = await alpaca_service.list_positions()
        except Exception as exc:
            logger.debug("positions failed for %s: %s", symbol, exc)
            return None
        for pos in positions or []:
            if str(pos.get("symbol", "")).upper() == symbol:
                try:
                    qty = float(pos.get("qty") or 0)
                    entry = float(pos.get("avg_entry_price") or pos.get("entry_price") or 0)
                    current = float(pos.get("current_price") or entry)
                    mv = float(pos.get("market_value") or qty * current)
                    upl = float(pos.get("unrealized_pl") or (current - entry) * qty)
                    return PositionSnapshot(
                        qty=qty,
                        avg_entry_price=entry,
                        market_value=mv,
                        unrealized_pl=upl,
                    )
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def _pct(curr: float, prev: float) -> float:
        if prev <= 0 or curr <= 0:
            return 0.0
        return ((curr - prev) / prev) * 100.0

    @staticmethod
    def _lookback_pct(points: list[dict[str, Any]], lookback: int) -> float:
        if len(points) < 2:
            return 0.0
        idx = max(0, len(points) - 1 - lookback)
        try:
            past = float(points[idx].get("close") or points[idx].get("price") or 0.0)
            now = float(points[-1].get("close") or points[-1].get("price") or 0.0)
            if past <= 0 or now <= 0:
                return 0.0
            return ((now - past) / past) * 100.0
        except (TypeError, ValueError):
            return 0.0


# ---------------------------------------------------------------------------
# Public service entry points
# ---------------------------------------------------------------------------


def list_personas_view() -> list[dict[str, object]]:
    return [p.public_view() for p in list_personas()]


async def analyze(
    session: AsyncSession,
    *,
    persona_id: str,
    symbol: str,
    question: Optional[str] = None,
    model: Optional[str] = None,
    builder: Optional[ContextBuilder] = None,
    router: Optional[Any] = None,
    lang: str = DEFAULT_LANG,
) -> dict[str, Any]:
    persona = get_persona(persona_id)
    builder = builder or LiveContextBuilder()
    router = router or OpenAILLMRouter()
    analyzer = Analyzer(router=router)
    target_lang = normalize_lang(lang)

    ctx = await builder.build(symbol, question=question)
    response = await analyzer.run(persona=persona, ctx=ctx, model=model, lang=target_lang)

    row = AgentAnalysis(
        persona_id=response.persona_id,
        symbol=response.symbol,
        question=question or "",
        verdict=response.verdict,
        confidence=response.confidence,
        reasoning_summary=response.reasoning_summary,
        key_factors_json=json.dumps([asdict(k) for k in response.key_factors]),
        follow_up_json=json.dumps(response.follow_up_questions),
        context_json=ctx.to_json_block(),
        model=model or "",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _serialize(row, response)


async def council(
    session: AsyncSession,
    *,
    persona_ids: Iterable[str],
    symbol: str,
    question: Optional[str] = None,
    model: Optional[str] = None,
    lang: str = DEFAULT_LANG,
) -> dict[str, Any]:
    """Run multiple personas against the same symbol.

    The context is built ONCE and reused across personas — saves N-1 round
    trips to alpaca/polygon/etc.
    """
    persona_ids = list(persona_ids)
    if not persona_ids:
        raise ValueError("persona_ids must not be empty")

    builder = LiveContextBuilder()
    ctx = await builder.build(symbol, question=question)
    router = OpenAILLMRouter()
    analyzer = Analyzer(router=router)
    target_lang = normalize_lang(lang)

    analyses: list[dict[str, Any]] = []
    for pid in persona_ids:
        persona = get_persona(pid)
        response = await analyzer.run(persona=persona, ctx=ctx, model=model, lang=target_lang)
        row = AgentAnalysis(
            persona_id=response.persona_id,
            symbol=response.symbol,
            question=question or "",
            verdict=response.verdict,
            confidence=response.confidence,
            reasoning_summary=response.reasoning_summary,
            key_factors_json=json.dumps([asdict(k) for k in response.key_factors]),
            follow_up_json=json.dumps(response.follow_up_questions),
            context_json=ctx.to_json_block(),
            model=model or "",
        )
        session.add(row)
        await session.flush()
        analyses.append(_serialize(row, response))
    await session.commit()
    return {"symbol": symbol, "analyses": analyses}


async def list_history(
    session: AsyncSession,
    *,
    symbol: Optional[str] = None,
    persona_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = select(AgentAnalysis).order_by(desc(AgentAnalysis.id))
    if symbol:
        stmt = stmt.where(AgentAnalysis.symbol == symbol.upper())
    if persona_id:
        stmt = stmt.where(AgentAnalysis.persona_id == persona_id)
    stmt = stmt.limit(max(1, min(limit, 200)))
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize(row: AgentAnalysis, response: PersonaResponse) -> dict[str, Any]:
    return {
        "id": row.id,
        "persona_id": response.persona_id,
        "symbol": response.symbol,
        "question": response.raw_question,
        "verdict": response.verdict,
        "confidence": response.confidence,
        "reasoning_summary": response.reasoning_summary,
        "key_factors": [asdict(k) for k in response.key_factors],
        "follow_up_questions": list(response.follow_up_questions),
        "model": row.model,
        "created_at": row.created_at,
    }


def _serialize_row(row: AgentAnalysis) -> dict[str, Any]:
    try:
        key_factors = json.loads(row.key_factors_json or "[]")
    except json.JSONDecodeError:
        key_factors = []
    try:
        follow_up = json.loads(row.follow_up_json or "[]")
    except json.JSONDecodeError:
        follow_up = []
    return {
        "id": row.id,
        "persona_id": row.persona_id,
        "symbol": row.symbol,
        "question": row.question,
        "verdict": row.verdict,
        "confidence": row.confidence,
        "reasoning_summary": row.reasoning_summary,
        "key_factors": key_factors,
        "follow_up_questions": follow_up,
        "model": row.model,
        "created_at": row.created_at,
    }
