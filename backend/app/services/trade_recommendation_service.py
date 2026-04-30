"""Synthesize a concrete trade recommendation from cost basis + signals + custom stops.

Inputs:
- position_costs row (if any) — gives avg_cost, shares, custom stop/tp
- chart_service current price
- signals_service latest signals (last 5 by recency)

Output: TradeRecommendationView with one-or-more TradeStanceView entries.
Each stance cites concrete numbers so the user can sanity-check.

This module is intentionally rule-based, not LLM-based. The AI Council
already runs the LLM-narrative path. This one gives a deterministic,
data-grounded second opinion the user can trust to be reproducible.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import chart_service, position_costs_service, signals_service


async def recommend_for_symbol(
    session: AsyncSession,
    *,
    symbol: str,
    broker_account_id: Optional[int] = None,
    range_name: str = "3mo",
) -> dict[str, Any]:
    """Build a concrete recommendation for one symbol.

    `broker_account_id` is optional — when provided, we look up the user's
    cost basis for that account; otherwise the recommendation is based on
    signals + price action alone (no position context).
    """
    symbol = symbol.upper()

    current_price = await _fetch_current_price(symbol, range_name)
    cost = (
        await position_costs_service.get_one(
            session, broker_account_id=broker_account_id, ticker=symbol
        )
        if broker_account_id is not None
        else None
    )
    has_position = bool(cost and cost.get("total_shares", 0) > 0)
    avg_cost = cost.get("avg_cost_basis") if cost else None
    shares = cost.get("total_shares") if cost else None
    stop = cost.get("custom_stop_loss") if cost else None
    tp = cost.get("custom_take_profit") if cost else None

    upnl_pct = None
    if has_position and current_price and avg_cost and avg_cost > 0:
        upnl_pct = ((current_price - avg_cost) / avg_cost) * 100.0

    signals_payload = await signals_service.compute_for_symbol(
        symbol, range_name=range_name
    )
    sigs = list(signals_payload.get("signals") or [])
    # Most recent first; cap at 5 for the rationale block.
    recent = sorted(sigs, key=lambda s: s.get("ts") or "", reverse=True)[:5]

    stances = _decide_stances(
        current_price=current_price,
        has_position=has_position,
        avg_cost=avg_cost,
        stop=stop,
        tp=tp,
        upnl_pct=upnl_pct,
        recent_signals=recent,
    )

    return {
        "symbol": symbol,
        "current_price": current_price,
        "has_position": has_position,
        "avg_cost_basis": avg_cost,
        "total_shares": shares,
        "unrealized_pnl_pct": upnl_pct,
        "custom_stop_loss": stop,
        "custom_take_profit": tp,
        "recent_signals_count": len(sigs),
        "stances": stances,
        "generated_at": datetime.now(timezone.utc),
    }


async def _fetch_current_price(symbol: str, range_name: str) -> Optional[float]:
    try:
        chart = await chart_service.get_symbol_chart(symbol, range_name=range_name)
    except Exception:
        return None
    points = (chart or {}).get("points") or []
    if not points:
        return None
    last = points[-1]
    try:
        return float(last.get("close") or last.get("price") or 0.0) or None
    except (TypeError, ValueError):
        return None


def _decide_stances(
    *,
    current_price: Optional[float],
    has_position: bool,
    avg_cost: Optional[float],
    stop: Optional[float],
    tp: Optional[float],
    upnl_pct: Optional[float],
    recent_signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rule-based synthesis. Each output stance dict matches TradeStanceView."""

    out: list[dict[str, Any]] = []

    # 1. Hard stops first — these are user-set and must override everything.
    if has_position and current_price is not None and stop is not None and current_price <= stop:
        out.append({
            "action": "stop_triggered",
            "confidence": 1.0,
            "headline": f"Stop-loss triggered at {current_price:.2f} (set: {stop:.2f})",
            "rationale": [
                f"Current {current_price:.2f} ≤ user stop {stop:.2f}.",
                f"Position avg cost: {avg_cost:.2f}." if avg_cost else "Position cost basis unknown.",
                "Recommend exit per pre-set risk plan; ignore conflicting bullish signals.",
            ],
        })
        return out  # Hard stop short-circuits.

    if has_position and current_price is not None and tp is not None and current_price >= tp:
        out.append({
            "action": "tp_triggered",
            "confidence": 1.0,
            "headline": f"Take-profit triggered at {current_price:.2f} (target: {tp:.2f})",
            "rationale": [
                f"Current {current_price:.2f} ≥ user target {tp:.2f}.",
                f"Unrealized P&L: {upnl_pct:.2f}%." if upnl_pct is not None else "P&L unknown.",
                "Recommend trim or exit per pre-set plan.",
            ],
        })
        return out

    # 2. Tally signal direction over recent events.
    buy_strength = sum(s.get("strength", 0) for s in recent_signals if s.get("direction") == "buy")
    sell_strength = sum(s.get("strength", 0) for s in recent_signals if s.get("direction") == "sell")
    buy_count = sum(1 for s in recent_signals if s.get("direction") == "buy")
    sell_count = sum(1 for s in recent_signals if s.get("direction") == "sell")
    interpretations = [s.get("interpretation", "") for s in recent_signals[:3]]

    if buy_strength == 0 and sell_strength == 0:
        out.append({
            "action": "hold" if has_position else "wait",
            "confidence": 0.4,
            "headline": "No recent technical signal triggers",
            "rationale": [
                f"Last 5 bars produced 0 signals.",
                f"Current price: {current_price:.2f}." if current_price else "Price unknown.",
                "Wait for a directional setup before acting.",
            ],
        })
        return out

    # 3. Decide based on dominance.
    if buy_strength > sell_strength * 1.3:  # need 30% edge to overcome inertia
        confidence = min(1.0, buy_strength / max(buy_count, 1))
        out.append({
            "action": "buy" if not has_position else "hold",
            "confidence": confidence,
            "headline": (
                f"Bullish bias from {buy_count} buy signal(s) "
                f"(strength sum {buy_strength:.2f})"
            ),
            "rationale": [
                f"Buy signals {buy_count} (sum {buy_strength:.2f}) "
                f"vs sell {sell_count} (sum {sell_strength:.2f}).",
                *[f"· {ip}" for ip in interpretations if ip],
                f"Current price: {current_price:.2f}." if current_price else "Price unknown.",
            ],
        })
    elif sell_strength > buy_strength * 1.3:
        confidence = min(1.0, sell_strength / max(sell_count, 1))
        out.append({
            "action": "sell" if has_position else "wait",
            "confidence": confidence,
            "headline": (
                f"Bearish bias from {sell_count} sell signal(s) "
                f"(strength sum {sell_strength:.2f})"
            ),
            "rationale": [
                f"Sell signals {sell_count} (sum {sell_strength:.2f}) "
                f"vs buy {buy_count} (sum {buy_strength:.2f}).",
                *[f"· {ip}" for ip in interpretations if ip],
                f"Current price: {current_price:.2f}." if current_price else "Price unknown.",
            ],
        })
    else:
        out.append({
            "action": "wait",
            "confidence": 0.3,
            "headline": "Mixed signals — wait for confluence",
            "rationale": [
                f"Buy strength {buy_strength:.2f} ≈ sell strength {sell_strength:.2f}.",
                *[f"· {ip}" for ip in interpretations if ip],
                "No directional edge; hold cash or existing position.",
            ],
        })

    return out
