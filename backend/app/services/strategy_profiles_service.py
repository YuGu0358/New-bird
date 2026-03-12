from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, StrategyProfile
from app.models import (
    StrategyAnalysisDraft,
    StrategyExecutionParameters,
    StrategyPreviewRequest,
    StrategySaveRequest,
)
from app.services import monitoring_service, openai_service
from app import runtime_settings

MAX_SAVED_STRATEGIES = 5
SECTOR_UNIVERSE_MAP = {
    "technology": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "ORCL", "CRM", "ADBE"],
    "semiconductors": ["NVDA", "AMD", "AVGO", "QCOM", "MU", "TSM", "AMAT", "LRCX"],
    "software": ["MSFT", "CRM", "NOW", "INTU", "ADBE", "SNOW", "MDB", "PLTR"],
    "cloud": ["AMZN", "MSFT", "GOOGL", "ORCL", "CRM", "SNOW", "MDB", "NOW"],
    "cybersecurity": ["CRWD", "PANW", "ZS", "FTNT", "OKTA", "CYBR"],
    "fintech": ["V", "MA", "PYPL", "SQ", "INTU", "COIN"],
    "mega_cap": ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA"],
    "etf": ["QQQ", "SPY", "VOO", "XLK", "VGT", "SMH"],
}
SECTOR_KEYWORDS = {
    "technology": ("科技", "technology", "tech"),
    "semiconductors": ("半导体", "芯片", "semiconductor", "chip"),
    "software": ("软件", "software", "saas"),
    "cloud": ("云", "cloud"),
    "cybersecurity": ("网络安全", "cybersecurity", "security"),
    "fintech": ("金融科技", "fintech", "支付"),
    "mega_cap": ("大盘科技", "mega cap", "megacap"),
    "etf": ("etf", "指数基金"),
}
DEFAULT_UNIVERSE = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "TSLA",
    "JPM",
    "V",
    "MA",
    "UNH",
    "HD",
    "PG",
    "XOM",
    "KO",
    "PEP",
    "DIS",
    "CRM",
    "NFLX",
    "COST",
]
DEFAULT_PARAMETERS = StrategyExecutionParameters(
    universe_symbols=DEFAULT_UNIVERSE,
    preferred_sectors=["technology", "mega_cap"],
    excluded_symbols=[],
    entry_drop_percent=2.0,
    add_on_drop_percent=2.0,
    initial_buy_notional=1000.0,
    add_on_buy_notional=100.0,
    max_daily_entries=3,
    max_add_ons=3,
    take_profit_target=80.0,
    stop_loss_percent=12.0,
    max_hold_days=30,
)
_SYMBOL_PATTERN = re.compile(r"\b[A-Z]{1,5}\b")
_SYMBOL_STOP_WORDS = {"USD", "ETF", "AI", "THE", "FOR", "AND", "OR"}


class StrategyRewriteResponse(BaseModel):
    suggested_name: str
    normalized_strategy: str
    improvement_points: list[str]
    risk_warnings: list[str]
    execution_notes: list[str]
    parameters: StrategyExecutionParameters


def _dedupe_symbols(values: list[str]) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for item in values:
        symbol = str(item or "").strip().upper()
        if not symbol or symbol in _SYMBOL_STOP_WORDS or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    return symbols


def _clamp_float(value: float | int | None, *, default: float, low: float, high: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return max(low, min(high, numeric))


def _clamp_int(value: float | int | None, *, default: int, low: int, high: int) -> int:
    try:
        numeric = int(round(float(value)))
    except (TypeError, ValueError):
        numeric = default
    return max(low, min(high, numeric))


def _normalize_parameters(parameters: StrategyExecutionParameters) -> StrategyExecutionParameters:
    preferred_sectors = _normalize_sector_names(parameters.preferred_sectors)
    excluded_symbols = _dedupe_symbols(parameters.excluded_symbols)
    symbols = _dedupe_symbols(parameters.universe_symbols)
    if not symbols and preferred_sectors:
        symbols = _build_universe_from_sectors(preferred_sectors)
    if not symbols:
        symbols = list(DEFAULT_PARAMETERS.universe_symbols)
    if excluded_symbols:
        symbols = [symbol for symbol in symbols if symbol not in set(excluded_symbols)]
    if not symbols:
        symbols = [symbol for symbol in DEFAULT_PARAMETERS.universe_symbols if symbol not in set(excluded_symbols)]

    return StrategyExecutionParameters(
        universe_symbols=symbols[:20],
        preferred_sectors=preferred_sectors,
        excluded_symbols=excluded_symbols[:20],
        entry_drop_percent=_clamp_float(
            parameters.entry_drop_percent,
            default=DEFAULT_PARAMETERS.entry_drop_percent,
            low=0.5,
            high=15.0,
        ),
        add_on_drop_percent=_clamp_float(
            parameters.add_on_drop_percent,
            default=DEFAULT_PARAMETERS.add_on_drop_percent,
            low=0.5,
            high=20.0,
        ),
        initial_buy_notional=_clamp_float(
            parameters.initial_buy_notional,
            default=DEFAULT_PARAMETERS.initial_buy_notional,
            low=50.0,
            high=100000.0,
        ),
        add_on_buy_notional=_clamp_float(
            parameters.add_on_buy_notional,
            default=DEFAULT_PARAMETERS.add_on_buy_notional,
            low=10.0,
            high=50000.0,
        ),
        max_daily_entries=_clamp_int(
            parameters.max_daily_entries,
            default=DEFAULT_PARAMETERS.max_daily_entries,
            low=1,
            high=20,
        ),
        max_add_ons=_clamp_int(
            parameters.max_add_ons,
            default=DEFAULT_PARAMETERS.max_add_ons,
            low=0,
            high=10,
        ),
        take_profit_target=_clamp_float(
            parameters.take_profit_target,
            default=DEFAULT_PARAMETERS.take_profit_target,
            low=5.0,
            high=10000.0,
        ),
        stop_loss_percent=_clamp_float(
            parameters.stop_loss_percent,
            default=DEFAULT_PARAMETERS.stop_loss_percent,
            low=1.0,
            high=50.0,
        ),
        max_hold_days=_clamp_int(
            parameters.max_hold_days,
            default=DEFAULT_PARAMETERS.max_hold_days,
            low=1,
            high=180,
        ),
    )


def _extract_candidate_symbols(description: str) -> list[str]:
    return _dedupe_symbols(_SYMBOL_PATTERN.findall(description.upper()))


def _normalize_sector_names(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        raw_value = str(item or "").strip().lower()
        if not raw_value:
            continue
        canonical = raw_value.replace("-", "_").replace(" ", "_")
        if canonical not in SECTOR_UNIVERSE_MAP:
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(canonical)
    return normalized


def _build_universe_from_sectors(sectors: list[str]) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for sector in sectors:
        for symbol in SECTOR_UNIVERSE_MAP.get(sector, []):
            if symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def _extract_candidate_sectors(description: str) -> list[str]:
    lowered = description.lower()
    sectors: list[str] = []
    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            sectors.append(sector)
    return sectors


def _fallback_strategy_analysis(description: str) -> StrategyAnalysisDraft:
    preferred_sectors = _extract_candidate_sectors(description) or list(DEFAULT_PARAMETERS.preferred_sectors)
    symbols = _extract_candidate_symbols(description)
    if not symbols:
        symbols = _build_universe_from_sectors(preferred_sectors)[:8]
    if not symbols:
        symbols = list(DEFAULT_PARAMETERS.universe_symbols[:8])
    normalized_strategy = (
        f"以 {', '.join(symbols[:8])} 作为主要观察股票池。"
        "当价格相对前收盘出现回撤时分批买入，随后按固定止盈、止损和最长持有周期执行退出。"
        "当前回退模式使用系统默认阈值，你可以继续修改描述后再次让 GPT 优化。"
    )

    return StrategyAnalysisDraft(
        suggested_name=f"{symbols[0]} 回撤策略" if symbols else "自定义回撤策略",
        original_description=description,
        normalized_strategy=normalized_strategy,
        improvement_points=[
            "补齐了明确的入场、加仓、止盈、止损和最长持有规则。",
            "把自由描述收敛成可执行参数，避免运行时解释歧义。",
            "保留了人工确认步骤，保存前不会直接改变机器人策略。",
        ],
        risk_warnings=[
            "当前回退模式没有使用 GPT 深度理解你的策略细节，参数采用默认安全值。",
            "如果你的策略依赖指标、做空、期权或多因子筛选，这个执行器目前不能完整表达。",
        ],
        execution_notes=[
            "当前执行器支持的核心参数是股票池、板块偏好、排除清单、每日最大开仓数、回撤买入阈值、加仓阈值、仓位金额和退出规则。",
            "确认并激活后，新的策略会在机器人下一次启动时生效。",
        ],
        parameters=StrategyExecutionParameters(
            **{
                **DEFAULT_PARAMETERS.model_dump(),
                "preferred_sectors": preferred_sectors,
                "universe_symbols": symbols[:20],
            }
        ),
        used_openai=False,
    )


def _build_strategy_prompt(description: str) -> str:
    supported_fields = (
        "universe_symbols, preferred_sectors, excluded_symbols, "
        "entry_drop_percent, add_on_drop_percent, initial_buy_notional, "
        "add_on_buy_notional, max_daily_entries, max_add_ons, "
        "take_profit_target, stop_loss_percent, max_hold_days"
    )
    return (
        "请把下面的自由描述交易想法，整理成适合纸面交易机器人执行的结构化策略。\n"
        "要求：\n"
        "1. 用中文输出。\n"
        "2. 保留用户原意，但把规则写清楚。\n"
        "3. 只能使用这些可执行字段："
        f"{supported_fields}。\n"
        "4. 如果用户描述超出当前执行器能力，请在 risk_warnings 或 execution_notes 中明确说明，并映射到最接近的可执行版本。\n"
        "5. 不要给出高杠杆、无限加仓或去掉风控的建议。\n"
        "6. preferred_sectors 只允许使用这些值：technology, semiconductors, software, cloud, cybersecurity, fintech, mega_cap, etf。\n"
        "7. universe_symbols 和 excluded_symbols 应该是股票代码数组；如果用户没给出明确股票池，可以给出合理默认值。\n"
        "8. max_daily_entries 代表单日最多允许新开仓多少个不同股票。\n\n"
        "用户原始描述：\n"
        f"{description}"
    )


def _analyze_strategy_sync(description: str) -> StrategyAnalysisDraft:
    client = openai_service.create_client()
    model_name = (
        runtime_settings.get_setting("OPENAI_CANDIDATE_MODEL", "gpt-4o-2024-08-06")
        or "gpt-4o-2024-08-06"
    )
    response = client.responses.parse(
        model=model_name,
        instructions=(
            "你是交易策略编辑助手。"
            "你负责把用户的想法规范化为更清晰、更保守、可执行的纸面交易策略。"
            "不要输出自动下单承诺，也不要给出越权的实盘建议。"
        ),
        input=[
            {
                "role": "user",
                "content": _build_strategy_prompt(description),
            }
        ],
        text_format=StrategyRewriteResponse,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI strategy analysis returned no structured payload.")

    normalized_parameters = _normalize_parameters(parsed.parameters)
    return StrategyAnalysisDraft(
        suggested_name=parsed.suggested_name.strip() or "GPT 优化策略",
        original_description=description,
        normalized_strategy=parsed.normalized_strategy.strip(),
        improvement_points=[item.strip() for item in parsed.improvement_points if item.strip()],
        risk_warnings=[item.strip() for item in parsed.risk_warnings if item.strip()],
        execution_notes=[item.strip() for item in parsed.execution_notes if item.strip()],
        parameters=normalized_parameters,
        used_openai=True,
    )


def _serialize_strategy(item: StrategyProfile) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "original_description": item.raw_description,
        "normalized_strategy": item.normalized_strategy,
        "improvement_points": json.loads(item.improvement_points_json),
        "risk_warnings": json.loads(item.risk_warnings_json),
        "execution_notes": json.loads(item.execution_notes_json),
        "parameters": json.loads(item.parameters_json),
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _build_preview_payload(
    normalized_strategy: str,
    parameters: StrategyExecutionParameters,
    likely_trade_candidates: list[dict],
) -> dict:
    scaled_capital_per_symbol = (
        parameters.initial_buy_notional
        + parameters.add_on_buy_notional * parameters.max_add_ons
    )
    max_new_capital_per_day = parameters.initial_buy_notional * parameters.max_daily_entries
    return {
        "universe_size": len(parameters.universe_symbols),
        "sample_symbols": parameters.universe_symbols[:8],
        "likely_trade_symbols": [item["symbol"] for item in likely_trade_candidates],
        "likely_trade_candidates": likely_trade_candidates,
        "preferred_sectors": parameters.preferred_sectors,
        "excluded_symbols": parameters.excluded_symbols,
        "max_new_positions_per_day": parameters.max_daily_entries,
        "max_capital_per_symbol": round(scaled_capital_per_symbol, 2),
        "max_new_capital_per_day": round(max_new_capital_per_day, 2),
        "max_total_capital_if_fully_scaled": round(
            scaled_capital_per_symbol * parameters.max_daily_entries,
            2,
        ),
        "entry_trigger_summary": (
            f"当股价相对前收盘回撤达到 {parameters.entry_drop_percent:.1f}% 时，"
            f"允许开新仓；单日最多新开 {parameters.max_daily_entries} 只股票。"
        ),
        "add_on_summary": (
            f"已有持仓继续回撤 {parameters.add_on_drop_percent:.1f}% 时允许加仓，"
            f"最多加仓 {parameters.max_add_ons} 次，每次 {parameters.add_on_buy_notional:.2f} 美元。"
        ),
        "exit_summary": (
            f"单只股票浮盈达到 {parameters.take_profit_target:.2f} 美元止盈，"
            f"回撤达到 {parameters.stop_loss_percent:.1f}% 止损，"
            f"最长持有 {parameters.max_hold_days} 天。"
        ),
        "restart_required": True,
        "normalized_strategy": normalized_strategy.strip(),
    }


def _format_percent(value: float | int | None) -> str:
    if not isinstance(value, (int, float)):
        return "暂无"
    return f"{float(value):.2f}%"


def _build_likely_trade_candidates(
    parameters: StrategyExecutionParameters,
    trend_map: dict[str, dict],
) -> list[dict]:
    ranked_items: list[dict] = []
    entry_threshold = max(parameters.entry_drop_percent, 0.1)

    for index, symbol in enumerate(parameters.universe_symbols):
        trend = trend_map.get(symbol, {})
        day_change = trend.get("day_change_percent")
        week_change = trend.get("week_change_percent")
        month_change = trend.get("month_change_percent")

        day_drop = abs(day_change) if isinstance(day_change, (int, float)) and day_change < 0 else 0.0
        week_drop = abs(week_change) if isinstance(week_change, (int, float)) and week_change < 0 else 0.0
        month_drop = abs(month_change) if isinstance(month_change, (int, float)) and month_change < 0 else 0.0

        if day_drop > 0:
            score = (day_drop / entry_threshold) * 10 + (week_drop * 0.6) + (month_drop * 0.3)
        else:
            score = (week_drop * 0.5) + (month_drop * 0.25) - (index * 0.01)

        if isinstance(day_change, (int, float)) and day_change <= -entry_threshold:
            note = (
                f"今日相对前收盘下跌 {_format_percent(abs(day_change))}，"
                f"已经达到入场阈值 {parameters.entry_drop_percent:.1f}%。"
            )
        elif isinstance(day_change, (int, float)) and day_change < 0:
            distance = max(parameters.entry_drop_percent - abs(day_change), 0.0)
            note = (
                f"今日下跌 {_format_percent(abs(day_change))}，"
                f"距离入场阈值还差 {distance:.2f}%。"
            )
        elif isinstance(week_change, (int, float)) and week_change < 0:
            note = (
                f"近一周回撤 {_format_percent(abs(week_change))}，"
                "如果日内继续走弱，会更接近触发条件。"
            )
        else:
            note = "当前更像观察对象，尚未接近日内回撤入场阈值。"

        ranked_items.append(
            {
                "symbol": symbol,
                "score": round(score, 2),
                "note": note,
                "day_change_percent": round(float(day_change), 2) if isinstance(day_change, (int, float)) else None,
                "week_change_percent": round(float(week_change), 2) if isinstance(week_change, (int, float)) else None,
                "month_change_percent": round(float(month_change), 2) if isinstance(month_change, (int, float)) else None,
            }
        )

    ranked_items.sort(
        key=lambda item: (
            float(item["score"]),
            item["day_change_percent"] if isinstance(item["day_change_percent"], (int, float)) else -999.0,
        ),
        reverse=True,
    )
    return ranked_items[:5]


async def analyze_strategy(description: str) -> StrategyAnalysisDraft:
    """Normalize a free-form strategy description into supported execution parameters."""

    normalized_description = str(description or "").strip()
    if not normalized_description:
        raise ValueError("请先输入策略描述。")

    if not openai_service.is_configured():
        return _fallback_strategy_analysis(normalized_description)

    try:
        return await asyncio.to_thread(_analyze_strategy_sync, normalized_description)
    except Exception:
        draft = _fallback_strategy_analysis(normalized_description)
        draft.risk_warnings.insert(0, "GPT 当前不可用，以下结果由本地回退规则生成。")
        return draft


async def list_strategies(session: AsyncSession) -> dict:
    """Return the saved strategy library ordered by active status and recency."""

    result = await session.execute(
        select(StrategyProfile).order_by(
            desc(StrategyProfile.is_active),
            desc(StrategyProfile.updated_at),
            desc(StrategyProfile.id),
        )
    )
    items = result.scalars().all()
    serialized = [_serialize_strategy(item) for item in items]
    active_item = next((item for item in serialized if item["is_active"]), None)
    return {
        "max_slots": MAX_SAVED_STRATEGIES,
        "items": serialized,
        "active_strategy_id": active_item["id"] if active_item is not None else None,
    }


async def save_strategy(session: AsyncSession, request: StrategySaveRequest) -> dict:
    """Persist a confirmed strategy, enforcing the 5-strategy limit."""

    name = str(request.name or "").strip()
    if not name:
        raise ValueError("保存前请先确认策略名称。")

    existing_items = (await session.execute(select(StrategyProfile))).scalars().all()
    if len(existing_items) >= MAX_SAVED_STRATEGIES:
        raise ValueError(f"最多只能保存 {MAX_SAVED_STRATEGIES} 套策略。请先删除旧策略。")

    if request.activate:
        for item in existing_items:
            item.is_active = False
            item.updated_at = datetime.now(timezone.utc)

    normalized_parameters = _normalize_parameters(request.parameters)
    now = datetime.now(timezone.utc)
    strategy = StrategyProfile(
        name=name,
        raw_description=request.original_description.strip(),
        normalized_strategy=request.normalized_strategy.strip(),
        parameters_json=json.dumps(normalized_parameters.model_dump(), ensure_ascii=False),
        improvement_points_json=json.dumps(request.improvement_points, ensure_ascii=False),
        risk_warnings_json=json.dumps(request.risk_warnings, ensure_ascii=False),
        execution_notes_json=json.dumps(request.execution_notes, ensure_ascii=False),
        is_active=request.activate,
        created_at=now,
        updated_at=now,
    )
    session.add(strategy)
    await session.commit()
    return await list_strategies(session)


async def update_strategy(
    session: AsyncSession,
    strategy_id: int,
    request: StrategySaveRequest,
) -> dict:
    """Update an existing saved strategy without consuming a new slot."""

    name = str(request.name or "").strip()
    if not name:
        raise ValueError("保存前请先确认策略名称。")

    result = await session.execute(select(StrategyProfile).where(StrategyProfile.id == strategy_id))
    strategy = result.scalars().first()
    if strategy is None:
        raise ValueError("没有找到要编辑的策略。")

    existing_items = (await session.execute(select(StrategyProfile))).scalars().all()
    now = datetime.now(timezone.utc)
    if request.activate:
        for item in existing_items:
            item.is_active = item.id == strategy_id
            item.updated_at = now

    normalized_parameters = _normalize_parameters(request.parameters)
    strategy.name = name
    strategy.raw_description = request.original_description.strip()
    strategy.normalized_strategy = request.normalized_strategy.strip()
    strategy.parameters_json = json.dumps(normalized_parameters.model_dump(), ensure_ascii=False)
    strategy.improvement_points_json = json.dumps(request.improvement_points, ensure_ascii=False)
    strategy.risk_warnings_json = json.dumps(request.risk_warnings, ensure_ascii=False)
    strategy.execution_notes_json = json.dumps(request.execution_notes, ensure_ascii=False)
    strategy.is_active = request.activate if request.activate else strategy.is_active
    strategy.updated_at = now

    await session.commit()
    return await list_strategies(session)


async def activate_strategy(session: AsyncSession, strategy_id: int) -> dict:
    """Mark one saved strategy as the active execution profile."""

    result = await session.execute(select(StrategyProfile).where(StrategyProfile.id == strategy_id))
    strategy = result.scalars().first()
    if strategy is None:
        raise ValueError("没有找到要激活的策略。")

    items = (await session.execute(select(StrategyProfile))).scalars().all()
    now = datetime.now(timezone.utc)
    for item in items:
        item.is_active = item.id == strategy_id
        item.updated_at = now
    await session.commit()
    return await list_strategies(session)


async def delete_strategy(session: AsyncSession, strategy_id: int) -> dict:
    """Delete a saved strategy from the library."""

    result = await session.execute(select(StrategyProfile).where(StrategyProfile.id == strategy_id))
    strategy = result.scalars().first()
    if strategy is None:
        raise ValueError("没有找到要删除的策略。")

    await session.delete(strategy)
    await session.commit()
    return await list_strategies(session)


async def preview_strategy(request: StrategyPreviewRequest) -> dict:
    """Summarize the effective execution footprint before saving a strategy."""

    normalized_parameters = _normalize_parameters(request.parameters)
    try:
        trend_map = await monitoring_service.fetch_trend_snapshots(normalized_parameters.universe_symbols)
    except Exception:
        trend_map = {}

    likely_trade_candidates = _build_likely_trade_candidates(normalized_parameters, trend_map)
    if not likely_trade_candidates:
        likely_trade_candidates = [
            {
                "symbol": symbol,
                "score": round(5.0 - index, 2),
                "note": "暂无实时趋势数据，先按策略股票池顺序作为优先观察对象。",
                "day_change_percent": None,
                "week_change_percent": None,
                "month_change_percent": None,
            }
            for index, symbol in enumerate(normalized_parameters.universe_symbols[:5])
        ]

    return _build_preview_payload(
        request.normalized_strategy,
        normalized_parameters,
        likely_trade_candidates,
    )


async def get_active_strategy_name() -> str:
    """Return the active strategy name, or the default engine label if none is active."""

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(StrategyProfile)
            .where(StrategyProfile.is_active.is_(True))
            .order_by(desc(StrategyProfile.updated_at), desc(StrategyProfile.id))
            .limit(1)
        )
        strategy = result.scalars().first()
        if strategy is None:
            return "系统默认 Strategy B"
        return strategy.name


async def get_active_strategy_parameters() -> StrategyExecutionParameters:
    """Load the active execution parameters for the runner."""

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(StrategyProfile)
            .where(StrategyProfile.is_active.is_(True))
            .order_by(desc(StrategyProfile.updated_at), desc(StrategyProfile.id))
            .limit(1)
        )
        strategy = result.scalars().first()
        if strategy is None:
            return DEFAULT_PARAMETERS

        payload = StrategyExecutionParameters.model_validate(json.loads(strategy.parameters_json))
        return _normalize_parameters(payload)


async def get_active_strategy_execution_profile() -> tuple[str, StrategyExecutionParameters]:
    """Return the active strategy label plus normalized execution parameters."""

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(StrategyProfile)
            .where(StrategyProfile.is_active.is_(True))
            .order_by(desc(StrategyProfile.updated_at), desc(StrategyProfile.id))
            .limit(1)
        )
        strategy = result.scalars().first()
        if strategy is None:
            return ("系统默认 Strategy B", DEFAULT_PARAMETERS)

        parameters = StrategyExecutionParameters.model_validate(json.loads(strategy.parameters_json))
        return (strategy.name, _normalize_parameters(parameters))
