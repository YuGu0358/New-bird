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
    indicators_service,
    market_research_service,
    options_chain_service,
    polygon_service,
    sector_rotation_service,
    social_signal_service,
)
from core.agents import (
    AnalysisContext,
    Analyzer,
    ContextBuilder,
    MarketRegime,
    NewsItem,
    OptionsFlowSnapshot,
    PersonaResponse,
    PositionSnapshot,
    PriceSnapshot,
    SocialSignalSnapshot,
    TechnicalsSnapshot,
    VolumeProfile,
    get_default_router,
    get_persona,
    list_personas,
)
from core.i18n import DEFAULT_LANG, normalize_lang

logger = logging.getLogger(__name__)


def _safe_float(value: object) -> Optional[float]:
    """Coerce to float; None on failure or None input."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
        # Pull the chart once and pass it around — both price math and
        # volume/turnover derive from the same series.
        chart_points = await self._fetch_chart_points(symbol)
        price = await self._build_price(symbol, chart_points)
        fundamentals = await self._build_fundamentals(symbol)
        recent_news = await self._build_news(symbol)
        social = await self._build_social(symbol)
        position = await self._build_position(symbol)
        technicals = await self._build_technicals(symbol)
        volume_profile = self._build_volume_profile(chart_points, fundamentals)
        options_flow = await self._build_options_flow(symbol)
        regime = await self._build_regime(fundamentals)

        return AnalysisContext(
            symbol=symbol,
            question=question,
            price=price,
            fundamentals=fundamentals,
            recent_news=recent_news,
            social=social,
            position=position,
            technicals=technicals,
            volume_profile=volume_profile,
            options_flow=options_flow,
            regime=regime,
            generated_at=datetime.now(timezone.utc),
        )

    async def _fetch_chart_points(self, symbol: str) -> list[dict[str, Any]]:
        try:
            chart = await chart_service.get_symbol_chart(symbol, range_name="3mo")
            return list((chart or {}).get("points") or [])
        except Exception as exc:
            logger.debug("chart failed for %s: %s", symbol, exc)
            return []

    async def _build_price(self, symbol: str, chart_points: list[dict[str, Any]]) -> PriceSnapshot:
        last = 0.0
        previous_close = 0.0
        try:
            previous_close = float(await polygon_service.get_previous_close(symbol))
        except Exception as exc:
            logger.debug("polygon previous close failed for %s: %s", symbol, exc)

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

    async def _build_technicals(self, symbol: str) -> Optional[TechnicalsSnapshot]:
        """Pull RSI(14) / MACD(12,26,9) / SMA(20) / EMA(20) / BBANDS(20,2) and
        keep just the latest non-None value of each canonical series."""

        async def _last_value(name: str, params: dict | None = None) -> float | None:
            try:
                payload = await indicators_service.compute_for_symbol(
                    symbol, name=name, range_name="3mo", params=params or {}
                )
            except Exception as exc:
                logger.debug("indicator %s failed for %s: %s", name, symbol, exc)
                return None
            series = (payload or {}).get("series") or {}
            # The 'value' series exists for sma/ema/rsi; macd/bbands use named series.
            for key in ("value",):
                vals = series.get(key)
                if vals:
                    for v in reversed(vals):
                        if v is not None:
                            return float(v)
            return None

        async def _last_dict(name: str, keys: tuple[str, ...]) -> dict[str, float | None]:
            try:
                payload = await indicators_service.compute_for_symbol(
                    symbol, name=name, range_name="3mo"
                )
            except Exception as exc:
                logger.debug("indicator %s failed for %s: %s", name, symbol, exc)
                return {k: None for k in keys}
            series_map = (payload or {}).get("series") or {}
            out: dict[str, float | None] = {}
            for key in keys:
                vals = series_map.get(key) or []
                last: float | None = None
                for v in reversed(vals):
                    if v is not None:
                        last = float(v)
                        break
                out[key] = last
            return out

        rsi = await _last_value("rsi", {"period": 14})
        sma = await _last_value("sma", {"period": 20})
        ema = await _last_value("ema", {"period": 20})
        macd_parts = await _last_dict("macd", ("macd", "signal", "histogram"))
        bb_parts = await _last_dict("bbands", ("upper", "middle", "lower"))

        # Bollinger position: 0 at lower band, 1 at upper. Helps the LLM see
        # squeeze / expansion without re-deriving from raw bands.
        bb_position: float | None = None
        upper, middle, lower = bb_parts.get("upper"), bb_parts.get("middle"), bb_parts.get("lower")
        last_close: float | None = None
        if upper is not None and lower is not None and upper > lower:
            # use middle as a stand-in for current — middle is SMA20 of close.
            anchor = middle if middle is not None else (upper + lower) / 2
            try:
                bb_position = max(0.0, min(1.0, (anchor - lower) / (upper - lower)))
                last_close = anchor
            except (TypeError, ValueError, ZeroDivisionError):
                bb_position = None

        # If we couldn't compute anything at all, return None so the UI shows
        # an empty-state badge rather than a row of dashes.
        snapshot = TechnicalsSnapshot(
            rsi_14=rsi,
            macd=macd_parts.get("macd"),
            macd_signal=macd_parts.get("signal"),
            macd_hist=macd_parts.get("histogram"),
            sma_20=sma,
            ema_20=ema,
            bbands_upper=upper,
            bbands_middle=middle,
            bbands_lower=lower,
            bbands_position=bb_position,
        )
        if all(getattr(snapshot, f) is None for f in (
            "rsi_14", "macd", "sma_20", "ema_20", "bbands_upper",
        )):
            return None
        return snapshot

    @staticmethod
    def _build_volume_profile(
        chart_points: list[dict[str, Any]],
        fundamentals: dict[str, object],
    ) -> Optional[VolumeProfile]:
        if not chart_points:
            return None
        volumes: list[int] = []
        for p in chart_points:
            try:
                v = int(p.get("volume") or 0)
            except (TypeError, ValueError):
                v = 0
            if v > 0:
                volumes.append(v)
        if not volumes:
            return None

        today_vol = volumes[-1]
        # 20-day average over the most recent 20 bars (excluding today).
        recent = volumes[-21:-1] if len(volumes) >= 21 else volumes[:-1]
        avg_20d = sum(recent) / len(recent) if recent else None
        ratio = (today_vol / avg_20d) if avg_20d and avg_20d > 0 else None

        turnover_pct: Optional[float] = None
        try:
            shares = fundamentals.get("shares_outstanding") if fundamentals else None
            if shares is not None and float(shares) > 0:
                turnover_pct = (today_vol / float(shares)) * 100.0
        except (TypeError, ValueError):
            turnover_pct = None

        return VolumeProfile(
            today_volume=today_vol,
            avg_volume_20d=avg_20d,
            today_vs_avg_x=ratio,
            turnover_pct=turnover_pct,
        )

    async def _build_options_flow(self, symbol: str) -> Optional[OptionsFlowSnapshot]:
        try:
            payload = await options_chain_service.get_gex_summary(symbol)
        except Exception as exc:
            logger.debug("options gex failed for %s: %s", symbol, exc)
            return None
        if not payload:
            return None
        # Compute P/C OI ratio from by_strike rollup (sum of put_oi / sum of call_oi).
        call_oi = 0
        put_oi = 0
        for row in (payload.get("by_strike") or []):
            try:
                call_oi += int(row.get("call_oi") or 0)
                put_oi += int(row.get("put_oi") or 0)
            except (TypeError, ValueError):
                continue
        pc_ratio = (put_oi / call_oi) if call_oi > 0 else None

        return OptionsFlowSnapshot(
            call_wall=_safe_float(payload.get("call_wall")),
            put_wall=_safe_float(payload.get("put_wall")),
            zero_gamma=_safe_float(payload.get("zero_gamma")),
            max_pain=_safe_float(payload.get("max_pain")),
            total_gex_dollar=_safe_float(payload.get("total_gex")),
            put_call_oi_ratio=pc_ratio,
            atm_iv=_safe_float(payload.get("atm_iv")),
        )

    async def _build_regime(self, fundamentals: dict[str, object]) -> Optional[MarketRegime]:
        sector = str(fundamentals.get("sector") or "").strip() if fundamentals else ""
        if not sector:
            return None
        try:
            rotation = await sector_rotation_service.get_sector_rotation()
        except Exception as exc:
            logger.debug("sector rotation failed: %s", exc)
            return None
        if not rotation:
            return None

        # Find the row matching this symbol's sector, then rank against peers.
        rows = list(rotation.get("rows") or rotation.get("sectors") or [])
        target_row: dict[str, Any] | None = None
        for r in rows:
            r_sector = str(r.get("sector") or r.get("name") or "").strip()
            if r_sector and r_sector.lower() == sector.lower():
                target_row = r
                break
        if target_row is None:
            return MarketRegime(sector=sector)

        # Rank by 5-day change descending; 1 = strongest.
        try:
            ranked = sorted(
                rows,
                key=lambda x: float(x.get("change_5d") or x.get("five_day") or 0),
                reverse=True,
            )
            rank = next(
                (i + 1 for i, r in enumerate(ranked) if r is target_row),
                None,
            )
        except (TypeError, ValueError):
            rank = None

        return MarketRegime(
            sector=sector,
            sector_5d_change_pct=_safe_float(
                target_row.get("change_5d") or target_row.get("five_day")
            ),
            sector_rank_among_11=rank,
            macro_tags=list(rotation.get("macro_tags") or [])[:6],
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
    router = router or get_default_router()
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
        action_plan_json=_action_plan_json(response),
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
    router = get_default_router()
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
            action_plan_json=_action_plan_json(response),
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
        "action_plan": asdict(response.action_plan) if response.action_plan else None,
        "model": row.model,
        "created_at": row.created_at,
    }


def _action_plan_json(response: PersonaResponse) -> str:
    """Serialize ActionPlan to JSON. Empty {} when persona declined."""
    if response.action_plan is None:
        return "{}"
    return json.dumps(asdict(response.action_plan))


def _action_plan_dict(blob: str | None) -> dict[str, Any] | None:
    """Best-effort deserialize from agent_analyses.action_plan_json."""
    if not blob or blob == "{}":
        return None
    try:
        decoded = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict) or not decoded:
        return None
    return decoded


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
        "action_plan": _action_plan_dict(getattr(row, "action_plan_json", None)),
        "model": row.model,
        "created_at": row.created_at,
    }
