from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import runtime_settings
from app.services.openai_service import create_client

logger = logging.getLogger(__name__)


# ---- Internal Pydantic models (used as OpenAI text_format target) ----------

class _AIPoint(BaseModel):
    timestamp: str = Field(..., description="ISO-8601 timestamp matching one of the input bars")
    price: float


class _AIAnnotation(BaseModel):
    kind: Literal["support", "resistance", "trendline", "note"]
    label: str
    points: list[_AIPoint]


class _AIResponse(BaseModel):
    annotations: list[_AIAnnotation]


_INSTRUCTIONS = (
    "你是一位资深技术分析师。给定一段 OHLCV 数据，请最多给出 5 条关键标注："
    "1) 支撑位 (support) 和阻力位 (resistance) 用横线，points 只填一个点的价格即可；"
    "2) 趋势线 (trendline) 用 points 中的两个端点；"
    "3) 形态备注 (note) 单点 + 简短说明；"
    "时间戳必须是输入 bars 中真实出现过的 timestamp。"
    "理由要简短中文，不要给出交易指令。"
)


def _to_millis(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _build_prompt(symbol: str, range_name: str, bars: list[dict[str, Any]]) -> str:
    head = bars[:3]
    tail = bars[-3:]
    lines = [
        f"标的: {symbol}, 区间: {range_name}, 共 {len(bars)} 根 K 线。",
        "前 3 根:",
    ]
    for bar in head:
        lines.append(
            f"  {bar['timestamp']} O={bar['open']} H={bar['high']} L={bar['low']} C={bar['close']} V={bar['volume']}"
        )
    lines.append("后 3 根:")
    for bar in tail:
        lines.append(
            f"  {bar['timestamp']} O={bar['open']} H={bar['high']} L={bar['low']} C={bar['close']} V={bar['volume']}"
        )
    closes = [bar["close"] for bar in bars]
    lines.append(f"最高/最低收盘: {max(closes):.2f} / {min(closes):.2f}")
    return "\n".join(lines)


def _annotate_chart_sync(
    symbol: str, range_name: str, bars: list[dict[str, Any]]
) -> dict[str, Any]:
    client = create_client()
    model_name = (
        runtime_settings.get_setting("OPENAI_CHART_MODEL", "gpt-4o-2024-08-06")
        or "gpt-4o-2024-08-06"
    )
    prompt = _build_prompt(symbol, range_name, bars)
    response = client.responses.parse(
        model=model_name,
        instructions=_INSTRUCTIONS,
        input=[{"role": "user", "content": prompt}],
        text_format=_AIResponse,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI returned no structured chart annotations.")
    annotations: list[dict[str, Any]] = []
    for item in parsed.annotations[:5]:
        try:
            points = [
                {"timestamp": _to_millis(p.timestamp), "price": float(p.price)}
                for p in item.points
                if p.timestamp
            ]
        except ValueError:
            logger.warning("Skipping annotation with malformed timestamp: %s", item)
            continue
        if not points:
            continue
        annotations.append({"kind": item.kind, "label": item.label.strip(), "points": points})
    return {"symbol": symbol.upper(), "range": range_name, "annotations": annotations}


async def annotate_chart(
    symbol: str, range_name: str, bars: list[dict[str, Any]]
) -> dict[str, Any]:
    """Ask OpenAI to annotate the supplied OHLCV bars with support/resistance/trendlines."""

    if not bars:
        raise ValueError("Cannot annotate an empty chart.")
    return await asyncio.to_thread(_annotate_chart_sync, symbol, range_name, bars)
