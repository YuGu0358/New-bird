"""Natural-language Q&A for the Factor Forge dashboard.

Uses OpenAI's tool-calling (function-calling) API. The LLM picks from a
small whitelist of predefined query tools we expose; it CANNOT write or
execute arbitrary Python. After the tool returns structured data, the
LLM produces a Chinese-language summary citing the data.

Why not PandasAI: CVE-2026-4998 (RCE) and CVE-2024-23752 — PandasAI lets
the LLM write+exec Python on the host. Tool-calling RAG is the safer
equivalent for our use case.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select

from app import runtime_settings
from app.db.engine import AsyncSessionLocal
from app.db.tables import (
    DailyActiveUniverse,
    DailyRecommendation,
    FactorGenerationStat,
    FactorRecord,
    PositionOverride,
)
from app.services.openai_service import create_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Whitelisted tools — the LLM can ONLY call these. Each is async + returns
# JSON-serialisable dicts/lists.
# ---------------------------------------------------------------------------


async def get_top_factors(n: int = 5) -> dict[str, Any]:
    """Top-N library factors by fitness (excludes quarantined)."""
    n = max(1, min(int(n), 50))
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorRecord)
                .where(FactorRecord.quarantined == False)  # noqa: E712
                .order_by(desc(FactorRecord.fitness))
                .limit(n)
            )
        ).scalars().all()
    return {
        "factors": [
            {
                "id": r.id, "formula": r.formula, "fitness": r.fitness,
                "ic_5d": r.ic_5d, "sharpe": r.sharpe,
                "max_drawdown": r.max_drawdown, "generation": r.generation,
            }
            for r in rows
        ]
    }


async def get_today_recommendations_summary(top_k: int = 10) -> dict[str, Any]:
    """Today's persisted buy/sell recommendations."""
    today = datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyRecommendation)
                .where(DailyRecommendation.date == today)
                .order_by(DailyRecommendation.action.desc(), DailyRecommendation.rank)
                .limit(top_k)
            )
        ).scalars().all()
    return {
        "date": today.isoformat(),
        "items": [
            {
                "symbol": r.symbol, "action": r.action,
                "entry_low": r.entry_low, "entry_high": r.entry_high,
                "stop_loss": r.stop_loss, "take_profit": r.take_profit,
                "holding_days": r.holding_days,
                "position_pct": r.position_pct, "confidence": r.confidence,
                "ensemble_score": r.ensemble_score,
                "reasoning": json.loads(r.reasoning_json or "[]"),
                "risk_signals": json.loads(r.risk_signals_json or "[]"),
                "rank": r.rank,
            }
            for r in rows
        ],
    }


async def explain_recommendation(symbol: str) -> dict[str, Any]:
    """Pull today's recommendation for one symbol with full reasoning + risks."""
    today = datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(DailyRecommendation).where(
                    DailyRecommendation.date == today,
                    DailyRecommendation.symbol == symbol.upper(),
                )
            )
        ).scalar_one_or_none()
    if row is None:
        return {"symbol": symbol.upper(), "found": False}
    return {
        "symbol": row.symbol, "found": True,
        "action": row.action,
        "entry": [row.entry_low, row.entry_high],
        "stop_loss": row.stop_loss, "take_profit": row.take_profit,
        "holding_days": row.holding_days,
        "position_pct": row.position_pct, "confidence": row.confidence,
        "ensemble_score": row.ensemble_score,
        "reasoning": json.loads(row.reasoning_json or "[]"),
        "risk_signals": json.loads(row.risk_signals_json or "[]"),
    }


async def get_active_universe_top(n: int = 10) -> dict[str, Any]:
    """Today's top-N active universe by composite activity score."""
    today = datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as session:
        # Fall back to most-recent if today not yet computed
        most_recent = (
            await session.execute(
                select(func.max(DailyActiveUniverse.date)).where(
                    DailyActiveUniverse.date <= today
                )
            )
        ).scalar()
        target = most_recent or today
        rows = (
            await session.execute(
                select(DailyActiveUniverse)
                .where(DailyActiveUniverse.date == target)
                .order_by(DailyActiveUniverse.rank)
                .limit(max(1, min(int(n), 100)))
            )
        ).scalars().all()
    return {
        "date": target.isoformat() if target else None,
        "items": [
            {"rank": r.rank, "symbol": r.symbol,
             "activity_score": r.activity_score, "dollar_volume": r.dollar_volume}
            for r in rows
        ],
    }


async def get_recent_fitness_trend(n_generations: int = 20) -> dict[str, Any]:
    """Recent generation stats for plotting / discussion."""
    n = max(1, min(int(n_generations), 200))
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorGenerationStat)
                .order_by(desc(FactorGenerationStat.generation))
                .limit(n)
            )
        ).scalars().all()
    rows = list(reversed(rows))
    return {
        "items": [
            {"generation": r.generation, "best_fitness": r.best_fitness,
             "median_fitness": r.median_fitness, "persisted_count": r.persisted_count,
             "evaluated_count": r.evaluated_count,
             "completed_at": r.completed_at.isoformat() if r.completed_at else None}
            for r in rows
        ]
    }


async def get_user_positions() -> dict[str, Any]:
    """All open user positions across broker accounts (without P&L)."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(select(PositionOverride))
        ).scalars().all()
    return {
        "items": [
            {"broker_account_id": r.broker_account_id, "ticker": r.ticker,
             "stop_price": r.stop_price, "take_profit_price": r.take_profit_price,
             "tier_override": r.tier_override, "notes": r.notes}
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# Tool registry — exposed to OpenAI's function-calling.
# ---------------------------------------------------------------------------


_TOOL_REGISTRY = {
    "get_top_factors": get_top_factors,
    "get_today_recommendations_summary": get_today_recommendations_summary,
    "explain_recommendation": explain_recommendation,
    "get_active_universe_top": get_active_universe_top,
    "get_recent_fitness_trend": get_recent_fitness_trend,
    "get_user_positions": get_user_positions,
}


_TOOL_SCHEMAS = [
    {
        "type": "function",
        "name": "get_top_factors",
        "description": "Return the top-N library factors by fitness (excludes quarantined).",
        "parameters": {
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "Number of factors", "default": 5}},
        },
    },
    {
        "type": "function",
        "name": "get_today_recommendations_summary",
        "description": "Today's buy/sell recommendations with entry/stop/target/confidence/reasoning/risk.",
        "parameters": {
            "type": "object",
            "properties": {"top_k": {"type": "integer", "default": 10}},
        },
    },
    {
        "type": "function",
        "name": "explain_recommendation",
        "description": "Get the FULL reasoning + risk signals for one symbol's today recommendation.",
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "Stock ticker e.g. AAPL"}},
            "required": ["symbol"],
        },
    },
    {
        "type": "function",
        "name": "get_active_universe_top",
        "description": "Today's top-N most active stocks by composite activity score.",
        "parameters": {
            "type": "object",
            "properties": {"n": {"type": "integer", "default": 10}},
        },
    },
    {
        "type": "function",
        "name": "get_recent_fitness_trend",
        "description": "Recent generation stats — best/median fitness over time, count persisted.",
        "parameters": {
            "type": "object",
            "properties": {"n_generations": {"type": "integer", "default": 20}},
        },
    },
    {
        "type": "function",
        "name": "get_user_positions",
        "description": "All current user position overrides (which symbols, with stops/take-profits).",
        "parameters": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_INSTRUCTIONS = (
    "你是 Factor Forge 的助手。用户用中文问关于因子库 / 今日建议 / 演化轨迹 / 持仓 的问题。"
    "你只能使用提供的工具来获取数据，禁止编造数字。\n"
    "工作流:\n"
    "1) 选一个或多个工具调用获取相关数据\n"
    "2) 用中文简明回答, 引用具体数字 (factor id / 公式 / 价格 / 比例 等)\n"
    "3) 如果工具返回为空, 直接告知用户库为空 / 没有当日数据\n"
    "回答要短, 重点突出, 用 markdown bullet 列举。"
)


def _model_name() -> str:
    return (
        runtime_settings.get_setting("OPENAI_QA_MODEL", "gpt-4o-2024-08-06")
        or "gpt-4o-2024-08-06"
    )


def _safety_check(question: str) -> str | None:
    """Reject obvious prompt-injection / destructive intent. Returns rejection
    reason or None if OK."""
    bad = ["rm -rf", "subprocess", "os.system", "import os", "eval(", "exec(",
           "open(", "__import__", "DROP TABLE", "DELETE FROM"]
    lower = question.lower()
    for kw in bad:
        if kw.lower() in lower:
            return f"问题包含可疑关键词 ({kw})，已拒绝"
    if len(question) > 500:
        return "问题过长 (>500 字符)，已拒绝"
    return None


async def answer_question(question: str, *, max_tool_calls: int = 4) -> dict[str, Any]:
    """Run the tool-calling loop. Return {answer, tool_calls, blocked?}."""
    rejection = _safety_check(question)
    if rejection:
        return {"answer": rejection, "tool_calls": [], "blocked": True}

    try:
        client = create_client()
    except Exception as exc:
        return {"answer": f"OpenAI 未配置: {exc}", "tool_calls": [], "blocked": True}

    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    tool_call_log: list[dict[str, Any]] = []
    model = _model_name()

    for _round in range(max_tool_calls):
        try:
            response = await asyncio.to_thread(
                client.responses.create,
                model=model,
                instructions=_INSTRUCTIONS,
                input=messages,
                tools=_TOOL_SCHEMAS,
            )
        except Exception as exc:
            logger.warning("OpenAI responses.create failed", exc_info=True)
            return {"answer": f"调用 LLM 失败: {exc}", "tool_calls": tool_call_log, "blocked": False}

        # Extract tool calls + final text from response.output items.
        items = getattr(response, "output", None) or []
        tool_calls_in_round = []
        text_parts: list[str] = []
        for item in items:
            kind = getattr(item, "type", None)
            if kind == "function_call":
                tool_calls_in_round.append(item)
            elif kind == "message":
                # message has content[] of {type: "output_text", text: ...}
                for c in (getattr(item, "content", None) or []):
                    if getattr(c, "type", None) == "output_text":
                        text_parts.append(getattr(c, "text", ""))

        # Final answer if no tools requested.
        if not tool_calls_in_round:
            answer = "\n".join(t for t in text_parts if t).strip() or "(空回答)"
            return {"answer": answer, "tool_calls": tool_call_log, "blocked": False}

        # Execute each requested tool call, append output to messages.
        for tc in tool_calls_in_round:
            tool_name = getattr(tc, "name", "")
            args_raw = getattr(tc, "arguments", "{}")
            call_id = getattr(tc, "call_id", None) or getattr(tc, "id", None)
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except json.JSONDecodeError:
                args = {}
            handler = _TOOL_REGISTRY.get(tool_name)
            if handler is None:
                result: Any = {"error": f"unknown tool: {tool_name}"}
            else:
                try:
                    result = await handler(**args)
                except TypeError as exc:
                    result = {"error": f"bad args: {exc}"}
                except Exception as exc:
                    logger.warning("tool %s failed", tool_name, exc_info=True)
                    result = {"error": str(exc)[:200]}
            tool_call_log.append({"name": tool_name, "args": args, "result_preview": str(result)[:300]})
            # Add the function call + its output to the conversation.
            messages.append({
                "type": "function_call",
                "name": tool_name,
                "arguments": json.dumps(args, ensure_ascii=False),
                "call_id": call_id,
            })
            messages.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result, ensure_ascii=False, default=str),
            })

    # Out of tool-call budget — synthesise an answer from what we have.
    return {
        "answer": "(达到工具调用上限，请重新问得更具体)",
        "tool_calls": tool_call_log,
        "blocked": False,
    }
