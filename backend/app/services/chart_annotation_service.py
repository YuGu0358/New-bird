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
    "你是一位资深的技术分析师, 你正在看一张专业的 K 线图 (蜡烛图)。"
    "图上 y 轴是价格, x 轴是时间, 红色蜡烛为下跌, 绿色为上涨。下方还有 MA 副图和成交量副图。"
    "请基于你看到的整张图, 给出最多 5 条**真正有价值**的标注:\n"
    "1) 支撑位 (support) — 画在图上多次反弹的低点附近;\n"
    "2) 阻力位 (resistance) — 画在图上多次被压制的高点附近;\n"
    "3) 趋势线 (trendline) — 必须连接两个真实的同向 pivot, 画出延伸方向;\n"
    "4) 形态备注 (note) — 双底/双顶/头肩/三角形等, 必须标在图上能看出形态的位置, 并写明判断依据;\n"
    "5) 标注的 timestamp 字段必须严格等于用户给你的合法时间戳列表中的某个值, 不要编造时间;\n"
    "6) 价格保留两位小数;\n"
    "7) 如果整张图没有清晰可标的形态, 宁可只返回 1-2 条, 不要为了凑数硬画;\n"
    "8) 不要给出任何交易指令; label 用一句简短中文说明你为什么标在这里。"
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
        f"标的: {symbol}, 区间: {range_name}, 共 {len(bars)} 根 K 线。",
        f"当前价: {last['close']:.2f} | RSI14: {tech.get('rsi14')} | "
        f"MACD hist: {tech.get('macd_hist')} | MA50: {tech.get('ma50')} | MA200: {tech.get('ma200')}",
        "",
        "你看到的图就是这条 K 线序列的渲染。请在图上识别支撑/阻力/趋势线/形态。",
        "返回时, timestamp 必须从下面这份合法时间戳列表中选 (这是图上每根 K 线对应的真实时间, ISO-8601):",
    ]
    for b in sampled:
        lines.append(f"  {b['timestamp']}  close={b['close']:.2f}")
    lines.append("")
    lines.append("已自动识别的近期 swing pivots (画支撑/阻力/趋势线时优先用这些):")
    for idx, b, kind in pivots[-12:]:
        lines.append(f"  [{kind}] {b['timestamp']} close={b['close']:.2f}")
    return "\n".join(lines)


def _annotate_chart_sync(
    symbol: str,
    range_name: str,
    bars: list[dict[str, Any]],
    image_data_url: str,
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
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_data_url},
                ],
            }
        ],
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
        annotations.append({
            "kind": item.kind,
            "label": item.label.strip(),
            "points": points,
            "group_id": "ai-annotation",
        })
    return {"symbol": symbol.upper(), "range": range_name, "annotations": annotations}


async def annotate_chart(
    symbol: str,
    range_name: str,
    bars: list[dict[str, Any]],
    image_data_url: str,
) -> dict[str, Any]:
    """Ask OpenAI vision to annotate the rendered chart image."""

    if not bars:
        raise ValueError("Cannot annotate an empty chart.")
    if not image_data_url or not image_data_url.startswith("data:image/"):
        raise ValueError("image_data_url must be a data URL (data:image/...)")
    return await asyncio.to_thread(
        _annotate_chart_sync, symbol, range_name, bars, image_data_url
    )
