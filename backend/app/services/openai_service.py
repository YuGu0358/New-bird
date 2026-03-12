from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel

from app import runtime_settings


class RankedCandidate(BaseModel):
    symbol: str
    rank: int
    reason: str


class CandidateSelectionResponse(BaseModel):
    picks: list[RankedCandidate]


def is_configured() -> bool:
    return bool(runtime_settings.get_setting("OPENAI_API_KEY", ""))


def _create_client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai is not installed.") from exc

    api_key = runtime_settings.get_required_setting(
        "OPENAI_API_KEY",
        "OPENAI_API_KEY is missing. Configure it in the settings page or backend/.env first.",
    )

    return OpenAI(api_key=api_key)


def _build_candidate_prompt(candidates: list[dict[str, Any]]) -> str:
    rows = []
    for item in candidates:
        rows.append(
            (
                f"{item['symbol']} | 类别={item['category']} | 综合分={item['score']:.2f} | "
                f"日涨跌={float(item['trend'].get('day_change_percent') or 0.0):.2f}% | "
                f"周涨跌={float(item['trend'].get('week_change_percent') or 0.0):.2f}% | "
                f"月涨跌={float(item['trend'].get('month_change_percent') or 0.0):.2f}%"
            )
        )

    return (
        "从下面的科技股和 ETF 候选名单中，挑选 5 只放入每日备选池。\n"
        "要求：\n"
        "1. 优先选择趋势最强、持续性更好的标的。\n"
        "2. 允许包含 ETF，但不要 5 只全是 ETF。\n"
        "3. 理由要简短、中文、偏研究视角，不要给出自动交易指令。\n"
        "4. 只从提供的候选里选，不要新增股票。\n\n"
        "候选数据：\n"
        f"{chr(10).join(rows)}"
    )


def _rank_candidates_sync(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    client = _create_client()
    model_name = (
        runtime_settings.get_setting("OPENAI_CANDIDATE_MODEL", "gpt-4o-2024-08-06")
        or "gpt-4o-2024-08-06"
    )
    response = client.responses.parse(
        model=model_name,
        instructions=(
            "你是股票研究助手。你只负责研究和候选池筛选，不负责自动下单。"
            "请基于给定的短中期趋势数据，在科技股和 ETF 中选出最值得关注的 5 只。"
        ),
        input=[
            {
                "role": "user",
                "content": _build_candidate_prompt(candidates),
            }
        ],
        text_format=CandidateSelectionResponse,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI candidate ranking returned no structured payload.")

    by_symbol = {str(item["symbol"]).upper(): item for item in candidates}
    ranked: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pick in sorted(parsed.picks, key=lambda item: item.rank):
        symbol = str(pick.symbol).upper()
        source = by_symbol.get(symbol)
        if source is None or symbol in seen:
            continue
        seen.add(symbol)
        ranked.append(
            {
                "symbol": symbol,
                "rank": len(ranked) + 1,
                "category": source["category"],
                "score": float(source["score"]),
                "reason": pick.reason.strip(),
                "trend": source["trend"],
            }
        )
        if len(ranked) >= 5:
            break

    return ranked


async def rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ask OpenAI to choose the final top-5 list from the pre-ranked shortlist."""

    if not candidates:
        return []

    return await asyncio.to_thread(_rank_candidates_sync, candidates)
