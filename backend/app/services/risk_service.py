"""Risk policy CRUD + factory that builds a RiskGuard from DB config.

Snapshot building (cash, equity, positions, realized PnL today) lives here
because both live runner and backtest service need it. We pull from
`alpaca_service` for live and from a `BacktestPortfolio` for backtest.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import RiskEvent, RiskPolicyConfig
from core.broker.base import Broker
from core.risk import (
    MaxDailyLossPolicy,
    MaxOpenPositionsPolicy,
    MaxPositionSizePolicy,
    MaxTotalExposurePolicy,
    PortfolioSnapshot,
    RiskCheck,
    RiskGuard,
    SymbolBlocklistPolicy,
)

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "max_position_size_usd": None,
    "max_total_exposure_pct": None,
    "max_open_positions": None,
    "max_daily_loss_usd": None,
    "blocklist": [],
}


async def get_or_create_config(session: AsyncSession) -> RiskPolicyConfig:
    config = await session.get(RiskPolicyConfig, 1)
    if config is None:
        config = RiskPolicyConfig(id=1, enabled=True, config_json=json.dumps(DEFAULT_CONFIG))
        session.add(config)
        await session.commit()
        await session.refresh(config)
    return config


def _config_to_view(config: RiskPolicyConfig) -> dict[str, Any]:
    body = json.loads(config.config_json or "{}")
    return {
        "enabled": bool(config.enabled),
        "max_position_size_usd": body.get("max_position_size_usd"),
        "max_total_exposure_pct": body.get("max_total_exposure_pct"),
        "max_open_positions": body.get("max_open_positions"),
        "max_daily_loss_usd": body.get("max_daily_loss_usd"),
        "blocklist": list(body.get("blocklist") or []),
        "updated_at": config.updated_at,
    }


async def get_config_view(session: AsyncSession) -> dict[str, Any]:
    config = await get_or_create_config(session)
    return _config_to_view(config)


async def update_config(
    session: AsyncSession,
    *,
    enabled: bool,
    max_position_size_usd: float | None,
    max_total_exposure_pct: float | None,
    max_open_positions: int | None,
    max_daily_loss_usd: float | None,
    blocklist: list[str],
) -> dict[str, Any]:
    config = await get_or_create_config(session)
    config.enabled = bool(enabled)
    config.config_json = json.dumps(
        {
            "max_position_size_usd": max_position_size_usd,
            "max_total_exposure_pct": max_total_exposure_pct,
            "max_open_positions": max_open_positions,
            "max_daily_loss_usd": max_daily_loss_usd,
            "blocklist": [str(s).strip().upper() for s in (blocklist or []) if str(s).strip()],
        }
    )
    await session.commit()
    await session.refresh(config)
    return _config_to_view(config)


async def list_recent_events(session: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    result = await session.execute(
        select(RiskEvent).order_by(desc(RiskEvent.id)).limit(max(1, min(limit, 200)))
    )
    return [
        {
            "id": ev.id,
            "occurred_at": ev.occurred_at,
            "policy_name": ev.policy_name,
            "decision": ev.decision,
            "reason": ev.reason,
            "symbol": ev.symbol,
            "side": ev.side,
            "notional": ev.notional,
            "qty": ev.qty,
        }
        for ev in result.scalars().all()
    ]


def build_policies_from_config(config_dict: dict[str, Any]) -> list[RiskCheck]:
    policies: list[RiskCheck] = []
    if config_dict.get("max_position_size_usd"):
        policies.append(MaxPositionSizePolicy(max_notional_per_symbol=float(config_dict["max_position_size_usd"])))
    if config_dict.get("max_total_exposure_pct"):
        policies.append(MaxTotalExposurePolicy(max_exposure_pct=float(config_dict["max_total_exposure_pct"])))
    if config_dict.get("max_open_positions"):
        policies.append(MaxOpenPositionsPolicy(max_positions=int(config_dict["max_open_positions"])))
    if config_dict.get("max_daily_loss_usd"):
        policies.append(MaxDailyLossPolicy(max_loss_usd=float(config_dict["max_daily_loss_usd"])))
    blocklist = config_dict.get("blocklist") or []
    if blocklist:
        policies.append(SymbolBlocklistPolicy(symbols=blocklist))
    return policies


def wrap_with_guard(
    broker: Broker,
    *,
    policies: list[RiskCheck],
    snapshot_provider: Callable[[], PortfolioSnapshot] | Callable[[], Awaitable[PortfolioSnapshot]],
) -> RiskGuard:
    return RiskGuard(broker, policies=policies, snapshot_provider=snapshot_provider)


async def record_event(
    session: AsyncSession,
    *,
    policy_name: str,
    decision: str,
    reason: str,
    symbol: str,
    side: str,
    notional: float | None,
    qty: float | None,
) -> None:
    session.add(
        RiskEvent(
            occurred_at=datetime.now(timezone.utc),
            policy_name=policy_name,
            decision=decision,
            reason=reason,
            symbol=symbol,
            side=side,
            notional=notional,
            qty=qty,
        )
    )
    await session.commit()
