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
    "你是一位资深的技术分析师。给定一段已降采样的 OHLCV K 线序列、自动识别的 swing pivots、以及当前的核心技术指标，"
    "请最多给出 5 条**有价值的**标注。规则:\n"
    "1) 支撑位 (support) 必须画在过去出现过明显反弹的低点附近, 而不是当前价附近。\n"
    "2) 阻力位 (resistance) 必须画在过去多次被压制的高点附近。\n"
    "3) 趋势线 (trendline) 必须连接两个真实存在的同向 pivot (例: 两个递增的 swing low 形成上升趋势线)。\n"
    "4) 形态备注 (note) 用于双底/双顶/头肩等形态, 必须带有简短的判断依据。\n"
    "5) 标注的 timestamp 字段必须严格等于 supplied bars 或 pivots 列表中出现过的 timestamp 字符串, 不要编造。\n"
    "6) 价格字段保留两位小数。\n"
    "7) 如果当前没有足够清晰的形态, 宁可少画 (返回 1-2 条) 也不要硬凑 5 条。\n"
    "8) 不要给出任何交易指令; label 用一句简短中文说明判断依据。"
)


def _to_millis(value: str) -> int:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _downsample_bars(bars: list[dict[str, Any]], target: int = 40) -> list[dict[str, Any]]:
    """Return at most ``target`` bars evenly spaced across the input.

    Always retains the first and last bars so the prompt sees the
    range endpoints. When the input is already smaller than target,
    returns it unchanged.
    """
    n = len(bars)
    if n <= target:
        return list(bars)
    step = max(1, n // target)
    sampled = [bars[i] for i in range(0, n, step)]
    if sampled[-1] is not bars[-1]:
        sampled.append(bars[-1])
    return sampled


def _find_swing_pivots(
    bars: list[dict[str, Any]], window: int = 5
) -> list[tuple[int, dict[str, Any], str]]:
    """Local min/max pivots over a centered window, by close price."""
    pivots: list[tuple[int, dict[str, Any], str]] = []
    closes = [float(b["close"]) for b in bars]
    for i in range(window, len(bars) - window):
        seg = closes[i - window : i + window + 1]
        c = closes[i]
        if c == min(seg) and seg.count(c) == 1:
            pivots.append((i, bars[i], "low"))
        elif c == max(seg) and seg.count(c) == 1:
            pivots.append((i, bars[i], "high"))
    return pivots


def _compute_technicals(closes: list[float]) -> dict[str, Any]:
    """Latest RSI(14), MACD histogram, MA50, MA200 — None when insufficient bars."""
    from core.indicators import compute_indicator

    out: dict[str, Any] = {}
    if len(closes) >= 15:
        rsi_series = compute_indicator("rsi", closes, params={"period": 14}).get("value") or []
        out["rsi14"] = rsi_series[-1] if rsi_series and rsi_series[-1] is not None else None
    if len(closes) >= 35:
        macd_series = compute_indicator("macd", closes, params={"fast": 12, "slow": 26, "signal": 9})
        hist = macd_series.get("histogram") or []
        out["macd_hist"] = hist[-1] if hist and hist[-1] is not None else None
    for period, key in ((50, "ma50"), (200, "ma200")):
        if len(closes) >= period:
            sma = compute_indicator("sma", closes, params={"period": period}).get("value") or []
            out[key] = sma[-1] if sma and sma[-1] is not None else None
        else:
            out[key] = None
    return out


def _build_prompt(symbol: str, range_name: str, bars: list[dict[str, Any]]) -> str:
    sampled = _downsample_bars(bars, target=40)
    pivots = _find_swing_pivots(bars, window=5)
    closes_full = [float(b["close"]) for b in bars]
    tech = _compute_technicals(closes_full)
    last = bars[-1]

    lines: list[str] = [
        f"标的: {symbol}, 区间: {range_name}, 共 {len(bars)} 根 K 线 (已降采样到 {len(sampled)} 根供你阅读)。",
        f"当前价: {last['close']:.2f} | RSI14: {tech.get('rsi14')} | MACD hist: {tech.get('macd_hist')} | "
        f"MA50: {tech.get('ma50')} | MA200: {tech.get('ma200')}",
        "",
        "降采样后的 K 线序列 (timestamp / O / H / L / C / V):",
    ]
    for b in sampled:
        lines.append(
            f"  {b['timestamp']} {b['open']:.2f} {b['high']:.2f} {b['low']:.2f} {b['close']:.2f} {b['volume']}"
        )
    lines.append("")
    lines.append("已自动识别的 swing pivots (你画线时优先使用这些点):")
    for idx, b, kind in pivots[-12:]:  # cap to last 12 to keep prompt size bounded
        lines.append(f"  [{kind}] index={idx} timestamp={b['timestamp']} close={b['close']:.2f}")
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
        annotations.append(
            {
                "kind": item.kind,
                "label": item.label.strip(),
                "points": points,
                "group_id": "ai-annotation",
            }
        )
    return {"symbol": symbol.upper(), "range": range_name, "annotations": annotations}


async def annotate_chart(
    symbol: str, range_name: str, bars: list[dict[str, Any]]
) -> dict[str, Any]:
    """Ask OpenAI to annotate the supplied OHLCV bars with support/resistance/trendlines."""

    if not bars:
        raise ValueError("Cannot annotate an empty chart.")
    return await asyncio.to_thread(_annotate_chart_sync, symbol, range_name, bars)
