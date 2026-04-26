"""Performance metrics computed from a backtest equity curve + trade list."""
from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Sequence

EquityPoint = tuple[datetime, float]
EquityCurve = Sequence[EquityPoint]


def _returns(curve: EquityCurve) -> list[float]:
    if len(curve) < 2:
        return []
    returns: list[float] = []
    for prev, curr in zip(curve, curve[1:]):
        prev_value = prev[1]
        curr_value = curr[1]
        if prev_value <= 0:
            continue
        returns.append((curr_value / prev_value) - 1.0)
    return returns


def total_return(curve: EquityCurve) -> float:
    if len(curve) < 2:
        return 0.0
    start = curve[0][1]
    end = curve[-1][1]
    if start <= 0:
        return 0.0
    return (end / start) - 1.0


def cagr(curve: EquityCurve) -> float:
    if len(curve) < 2:
        return 0.0
    start_ts, start_value = curve[0]
    end_ts, end_value = curve[-1]
    if start_value <= 0 or end_value <= 0:
        return 0.0
    days = (end_ts - start_ts).total_seconds() / 86400.0
    if days < 1:
        return 0.0
    years = days / 365.25
    if years <= 0:
        return 0.0
    return (end_value / start_value) ** (1.0 / years) - 1.0


def max_drawdown(curve: EquityCurve) -> float:
    if not curve:
        return 0.0
    peak = curve[0][1]
    worst = 0.0
    for _, value in curve:
        if value > peak:
            peak = value
        if peak <= 0:
            continue
        drawdown = (value - peak) / peak
        if drawdown < worst:
            worst = drawdown
    return worst


def sharpe_ratio(curve: EquityCurve, *, periods_per_year: int = 252, risk_free: float = 0.0) -> float:
    rs = _returns(curve)
    if len(rs) < 2:
        return 0.0
    excess = [r - (risk_free / periods_per_year) for r in rs]
    mean = statistics.fmean(excess)
    stdev = statistics.pstdev(excess)
    if stdev == 0:
        return 0.0
    return mean / stdev * math.sqrt(periods_per_year)


def sortino_ratio(curve: EquityCurve, *, periods_per_year: int = 252, risk_free: float = 0.0) -> float:
    rs = _returns(curve)
    if len(rs) < 2:
        return 0.0
    excess = [r - (risk_free / periods_per_year) for r in rs]
    mean = statistics.fmean(excess)
    downside = [r for r in excess if r < 0]
    if not downside:
        # No losing periods → infinite ratio in pure form. Cap at 100 for sanity.
        return 100.0 if mean > 0 else 0.0
    downside_dev = math.sqrt(sum(d * d for d in downside) / len(downside))
    if downside_dev == 0:
        return 0.0
    return mean / downside_dev * math.sqrt(periods_per_year)


def calmar_ratio(curve: EquityCurve) -> float:
    annual = cagr(curve)
    dd = abs(max_drawdown(curve))
    if dd == 0:
        return 100.0 if annual > 0 else 0.0
    return annual / dd


def win_rate(pnl_per_trade: Sequence[float]) -> float:
    if not pnl_per_trade:
        return 0.0
    wins = sum(1 for p in pnl_per_trade if p > 0)
    return wins / len(pnl_per_trade)


def profit_factor(pnl_per_trade: Sequence[float]) -> float:
    gross_profit = sum(p for p in pnl_per_trade if p > 0)
    gross_loss = -sum(p for p in pnl_per_trade if p < 0)
    if gross_loss == 0:
        return 100.0 if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_metrics(
    curve: EquityCurve,
    *,
    pnl_per_trade: Sequence[float],
    periods_per_year: int = 252,
) -> dict[str, float]:
    return {
        "total_return": total_return(curve),
        "cagr": cagr(curve),
        "sharpe": sharpe_ratio(curve, periods_per_year=periods_per_year),
        "sortino": sortino_ratio(curve, periods_per_year=periods_per_year),
        "max_drawdown": max_drawdown(curve),
        "calmar": calmar_ratio(curve),
        "win_rate": win_rate(pnl_per_trade),
        "profit_factor": profit_factor(pnl_per_trade),
    }
