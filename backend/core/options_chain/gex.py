"""GEX rollup — Call Wall / Put Wall / Zero Gamma / Max Pain.

Inputs: a list of OptionContract rows (all expiries already merged).
Outputs: a GexSummary that maps 1:1 to what the frontend renders.

Conventions (pragmatic, mirror Tradewell):
- Call Wall  = strike with highest call GEX
- Put Wall   = strike with most-negative put GEX
- Zero Gamma = strike where running cumulative net GEX flips sign
- Max Pain   = strike that minimises total ITM intrinsic value at the
               nearest-expiry chain (max-pain is per-expiry by definition)
- Total GEX  = sum across all rows in $

Standard equity option contract = 100 shares per contract.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class OptionContract:
    expiry: date
    strike: float
    option_type: str  # "C" or "P"
    open_interest: int
    volume: int
    iv: float | None
    delta: float | None
    gamma: float | None
    last: float | None = None
    bid: float | None = None
    ask: float | None = None


@dataclass
class GexSummary:
    ticker: str
    spot: float
    call_wall: float | None
    put_wall: float | None
    zero_gamma: float | None
    max_pain: float | None
    total_gex: float
    call_gex_total: float
    put_gex_total: float
    by_strike: list[dict[str, Any]] = field(default_factory=list)
    by_expiry: list[dict[str, Any]] = field(default_factory=list)


CONTRACT_MULTIPLIER = 100  # standard US equity option


def _per_contract_gex(c: OptionContract, spot: float) -> float:
    """Per-contract gamma exposure in $.

    GEX = sign · gamma · OI · contract_multiplier · spot²
    sign = +1 for calls (dealers short), −1 for puts.
    """
    if c.gamma is None or c.open_interest is None or spot <= 0:
        return 0.0
    sign = 1 if c.option_type.upper() == "C" else -1
    return sign * c.gamma * c.open_interest * CONTRACT_MULTIPLIER * spot * spot


def _per_expiry_max_pain(rows: list[OptionContract], expiry: date) -> float | None:
    expiry_rows = [r for r in rows if r.expiry == expiry and r.open_interest]
    if not expiry_rows:
        return None
    candidates = sorted({r.strike for r in expiry_rows})
    best_strike: float | None = None
    best_pain = float("inf")
    for s in candidates:
        pain = 0.0
        for r in expiry_rows:
            oi = r.open_interest or 0
            if r.option_type.upper() == "C":
                pain += max(0.0, s - r.strike) * oi
            else:
                pain += max(0.0, r.strike - s) * oi
        if pain < best_pain:
            best_pain = pain
            best_strike = s
    return best_strike


def _zero_gamma(by_strike: list[dict[str, Any]]) -> float | None:
    if not by_strike:
        return None
    sorted_strikes = sorted(by_strike, key=lambda x: x["strike"])
    running = 0.0
    prev: dict[str, Any] | None = None
    for s in sorted_strikes:
        new_running = running + s["net_gex"]
        if prev is not None and (running > 0) != (new_running > 0):
            if abs(new_running - running) > 1e-9:
                t = -running / (new_running - running)
                return prev["strike"] + t * (s["strike"] - prev["strike"])
            return s["strike"]
        running = new_running
        prev = s
    return None


def summarize_chain(
    *,
    ticker: str,
    spot: float,
    contracts: list[OptionContract],
) -> GexSummary | None:
    if not contracts:
        return None

    per_strike: dict[float, dict[str, float]] = defaultdict(
        lambda: {
            "call_gex": 0.0,
            "put_gex": 0.0,
            "call_oi": 0.0,
            "put_oi": 0.0,
            "call_volume": 0.0,
            "put_volume": 0.0,
        }
    )

    for c in contracts:
        if c.gamma is None or c.open_interest is None:
            continue
        gex = _per_contract_gex(c, spot)
        oi = float(c.open_interest or 0)
        vol = float(c.volume or 0)
        if c.option_type.upper() == "C":
            per_strike[c.strike]["call_gex"] += gex
            per_strike[c.strike]["call_oi"] += oi
            per_strike[c.strike]["call_volume"] += vol
        else:
            per_strike[c.strike]["put_gex"] += gex
            per_strike[c.strike]["put_oi"] += oi
            per_strike[c.strike]["put_volume"] += vol

    by_strike = [
        {
            "strike": s,
            "call_gex": agg["call_gex"],
            "put_gex": agg["put_gex"],
            "net_gex": agg["call_gex"] + agg["put_gex"],
            "call_oi": int(agg["call_oi"]),
            "put_oi": int(agg["put_oi"]),
            "oi": int(agg["call_oi"] + agg["put_oi"]),
            "call_volume": int(agg["call_volume"]),
            "put_volume": int(agg["put_volume"]),
        }
        for s, agg in per_strike.items()
    ]
    by_strike.sort(key=lambda x: x["strike"])

    call_wall = (
        max(by_strike, key=lambda x: x["call_gex"])["strike"]
        if any(x["call_gex"] > 0 for x in by_strike)
        else None
    )
    put_wall = (
        min(by_strike, key=lambda x: x["put_gex"])["strike"]
        if any(x["put_gex"] < 0 for x in by_strike)
        else None
    )

    zero_gamma = _zero_gamma(by_strike)

    expiries = sorted({c.expiry for c in contracts})
    max_pain = _per_expiry_max_pain(contracts, expiries[0]) if expiries else None

    by_expiry: list[dict[str, Any]] = []
    for exp in expiries:
        exp_rows = [c for c in contracts if c.expiry == exp]
        gex_sum = sum(_per_contract_gex(c, spot) for c in exp_rows)
        by_expiry.append(
            {
                "expiry": exp.isoformat(),
                "total_gex": gex_sum,
                "max_pain": _per_expiry_max_pain(contracts, exp),
                "contracts": len(exp_rows),
            }
        )

    call_gex_total = sum(s["call_gex"] for s in by_strike)
    put_gex_total = sum(s["put_gex"] for s in by_strike)
    total_gex = call_gex_total + put_gex_total

    return GexSummary(
        ticker=ticker.upper(),
        spot=spot,
        call_wall=call_wall,
        put_wall=put_wall,
        zero_gamma=zero_gamma,
        max_pain=max_pain,
        total_gex=total_gex,
        call_gex_total=call_gex_total,
        put_gex_total=put_gex_total,
        by_strike=by_strike,
        by_expiry=by_expiry,
    )
