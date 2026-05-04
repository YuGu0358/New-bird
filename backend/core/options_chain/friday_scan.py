"""Friday OPEX pinning scanner — verdict for "should I bet pinning this Fri?"

Borrowed from Tradewell's `friday_scanner.py`. We compute the same composite
score (0..100) but adapted to Newbird's OptionContract dataclass instead of
the DB-backed OptionSnapshot rows.

Score components:
  A. Wall geometry (40 pts)
     +20  spot inside [put_wall, call_wall]
     +20  nearest wall < 2% from spot
  B. Wall strength (30 pts)
     +10  either wall concentration > 5% (within ±15% spot band)
     +10  either wall salience > 10× median strike OI
     +10  Friday total |GEX| / ADV > 10% (only if adv_dollar provided)
  C. Volatility context (20 pts)
     +20  expected ±1σ move < nearest-wall-distance in dollars
  D. Time decay (10 pts)
     +10  DTE ≤ 1
     + 5  DTE == 2

Verdict:
  ≥ 70: BET PINNING
  40..69: MIXED
  < 40: SKIP

When `adv_dollar` is unavailable the scanner skips the GEX-pressure check —
score caps out at 90 instead of 100.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from core.options_chain.gex import OptionContract, _per_contract_gex


@dataclass
class WallSummary:
    strike: float | None
    oi: int
    concentration_pct: float | None
    salience_mult: float | None
    pressure_pct: float | None
    distance_pct: float | None
    gex_dollar: float
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FridayScan:
    ticker: str
    spot: float
    target_expiry: str  # ISO date
    dte_calendar: int
    has_data: bool

    atm_iv: float | None
    expected_move: float | None
    expected_low: float | None
    expected_high: float | None

    contract_count: int
    total_chain_oi: int
    median_strike_oi: int
    total_friday_gex: float
    friday_gex_pressure_pct: float | None
    adv_dollar: float | None

    call_wall: WallSummary
    put_wall: WallSummary
    max_pain: float | None
    put_call_oi_ratio: float | None

    pinning_score: int
    verdict: str  # "BET" | "MIXED" | "SKIP"
    reasons: list[str] = field(default_factory=list)

    suggested_short_call: float | None = None
    suggested_short_put: float | None = None
    breakeven_low: float | None = None
    breakeven_high: float | None = None


def _atm_iv(rows: list[OptionContract], spot: float) -> float | None:
    if not rows or spot <= 0:
        return None
    nearest_strike = min({r.strike for r in rows}, key=lambda s: abs(s - spot))
    ivs = [r.iv for r in rows if r.strike == nearest_strike and r.iv is not None]
    return sum(ivs) / len(ivs) if ivs else None


def _expected_move(spot: float, atm_iv: float, dte: int) -> float:
    t_yrs = max(dte / 365.0, 1 / 365.0)
    return spot * atm_iv * math.sqrt(t_yrs)


def _max_pain(rows: list[OptionContract]) -> float | None:
    candidates = sorted({r.strike for r in rows})
    if not candidates:
        return None
    best_strike: float | None = None
    best_pain = float("inf")
    for s in candidates:
        pain = 0.0
        for r in rows:
            oi = r.open_interest or 0
            if r.option_type.upper() == "C":
                pain += max(0.0, s - r.strike) * oi
            else:
                pain += max(0.0, r.strike - s) * oi
        if pain < best_pain:
            best_pain = pain
            best_strike = s
    return best_strike


def _build_walls(
    rows: list[OptionContract],
    spot: float,
    adv_dollar: float | None,
) -> tuple[WallSummary, WallSummary, int, int, int]:
    lo = spot * 0.85
    hi = spot * 1.15
    by_strike: dict[float, dict[str, float]] = {}
    for r in rows:
        if r.strike < lo or r.strike > hi:
            continue
        agg = by_strike.setdefault(
            r.strike, {"call_oi": 0.0, "put_oi": 0.0, "call_gex": 0.0, "put_gex": 0.0}
        )
        oi = float(r.open_interest or 0)
        gex = _per_contract_gex(r, spot)
        if r.option_type.upper() == "C":
            agg["call_oi"] += oi
            agg["call_gex"] += gex
        else:
            agg["put_oi"] += oi
            agg["put_gex"] += gex

    if not by_strike:
        empty = WallSummary(None, 0, None, None, None, None, 0.0, {})
        return empty, empty, 0, 0, 0

    strikes_list = [
        {**v, "strike": k, "total_oi": v["call_oi"] + v["put_oi"]}
        for k, v in by_strike.items()
    ]
    total_oi = int(sum(s["total_oi"] for s in strikes_list))
    median_oi = int(statistics.median([s["total_oi"] for s in strikes_list])) if strikes_list else 0

    def _wall(side: str) -> WallSummary:
        if side == "call":
            cand = max(strikes_list, key=lambda s: s["call_gex"])
            wall_oi = int(cand["call_oi"])
            gex = abs(cand["call_gex"])
        else:
            cand = min(strikes_list, key=lambda s: s["put_gex"])
            wall_oi = int(cand["put_oi"])
            gex = abs(cand["put_gex"])
        if wall_oi <= 0:
            return WallSummary(cand["strike"], 0, 0.0, 0.0, 0.0, None, 0.0, {})
        concentration = (wall_oi / total_oi * 100) if total_oi > 0 else 0
        salience = (wall_oi / median_oi) if median_oi > 0 else None
        pressure = (gex / adv_dollar * 100) if (adv_dollar and adv_dollar > 0) else None
        distance = abs(cand["strike"] - spot) / spot * 100 if spot > 0 else None
        return WallSummary(
            strike=cand["strike"],
            oi=wall_oi,
            concentration_pct=concentration,
            salience_mult=salience,
            pressure_pct=pressure,
            distance_pct=distance,
            gex_dollar=gex,
            raw={
                "wall_oi": wall_oi,
                "total_oi": total_oi,
                "median_oi": median_oi,
                "gex_dollar": gex,
                "adv_dollar": adv_dollar,
            },
        )

    call_wall = _wall("call")
    put_wall = _wall("put")
    return call_wall, put_wall, total_oi, median_oi, len(strikes_list)


def _score(
    spot: float,
    call_wall: WallSummary,
    put_wall: WallSummary,
    expected_move: float | None,
    friday_gex_pressure: float | None,
    dte: int,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    inside_fence = (
        put_wall.strike is not None
        and call_wall.strike is not None
        and put_wall.strike < spot < call_wall.strike
    )
    if inside_fence:
        score += 20
        reasons.append(f"spot is fenced between walls (put={put_wall.strike}, call={call_wall.strike}) (+20)")

    nearest_dist = None
    if call_wall.distance_pct is not None and put_wall.distance_pct is not None:
        nearest_dist = min(call_wall.distance_pct, put_wall.distance_pct)
    if nearest_dist is not None and nearest_dist < 2.0:
        score += 20
        reasons.append(f"nearest wall is only {nearest_dist:.2f}% from spot (<2% → +20)")

    max_conc = max(call_wall.concentration_pct or 0, put_wall.concentration_pct or 0)
    if max_conc > 5.0:
        score += 10
        reasons.append(f"strongest wall concentration {max_conc:.1f}% of chain OI (>5% → +10)")

    max_sal = max(call_wall.salience_mult or 0, put_wall.salience_mult or 0)
    if max_sal > 10.0:
        score += 10
        reasons.append(f"strongest wall salience {max_sal:.1f}× the median strike (>10× → +10)")

    if friday_gex_pressure is not None and friday_gex_pressure > 10.0:
        score += 10
        reasons.append(f"Friday |GEX| is {friday_gex_pressure:.1f}% of ADV (>10% → +10)")

    if (
        expected_move is not None
        and nearest_dist is not None
        and call_wall.strike is not None
        and put_wall.strike is not None
    ):
        nearest_dist_dollars = (nearest_dist / 100) * spot
        if expected_move < nearest_dist_dollars:
            score += 20
            reasons.append(
                f"expected ±1σ move ${expected_move:.2f} < distance to nearest wall ${nearest_dist_dollars:.2f} (+20)"
            )

    if dte <= 1:
        score += 10
        reasons.append(f"DTE={dte}, gamma is at its peak (+10)")
    elif dte == 2:
        score += 5
        reasons.append("DTE=2, gamma still elevated (+5)")

    return score, reasons


def _verdict(score: int) -> str:
    if score >= 70:
        return "BET"
    if score >= 40:
        return "MIXED"
    return "SKIP"


def scan_pinning(
    *,
    ticker: str,
    spot: float,
    contracts: list[OptionContract],
    target_expiry: date,
    today: date | None = None,
    adv_dollar: float | None = None,
) -> FridayScan:
    """Score the pinning probability for a single expiry. Spot ≤ 0 still
    returns a valid (empty) FridayScan with verdict SKIP."""
    today = today or date.today()
    rows = [c for c in contracts if c.expiry == target_expiry]
    has_data = bool(rows) and spot > 0
    dte = max((target_expiry - today).days, 0)

    atm_iv = _atm_iv(rows, spot) if has_data else None
    em = _expected_move(spot, atm_iv, dte) if (has_data and atm_iv) else None

    call_wall, put_wall, total_oi, median_oi, _strike_ct = (
        _build_walls(rows, spot, adv_dollar) if has_data else
        (WallSummary(None, 0, None, None, None, None, 0.0, {}),
         WallSummary(None, 0, None, None, None, None, 0.0, {}),
         0, 0, 0)
    )

    total_friday_gex = sum(_per_contract_gex(c, spot) for c in rows) if has_data else 0.0
    pressure = (
        abs(total_friday_gex) / adv_dollar * 100
        if (adv_dollar and adv_dollar > 0)
        else None
    )

    score, reasons = (_score(spot, call_wall, put_wall, em, pressure, dte) if has_data else (0, []))
    if not has_data:
        reasons.append("No contracts available for this expiry — score = 0")

    calls_total_oi = sum(int(r.open_interest or 0) for r in rows if r.option_type.upper() == "C")
    puts_total_oi = sum(int(r.open_interest or 0) for r in rows if r.option_type.upper() == "P")
    pc_ratio = (puts_total_oi / calls_total_oi) if calls_total_oi > 0 else None

    suggested_short_call = call_wall.strike if call_wall.strike else None
    suggested_short_put = put_wall.strike if put_wall.strike else None

    return FridayScan(
        ticker=ticker.upper(),
        spot=spot,
        target_expiry=target_expiry.isoformat(),
        dte_calendar=dte,
        has_data=has_data,
        atm_iv=atm_iv,
        expected_move=em,
        expected_low=spot - em if em else None,
        expected_high=spot + em if em else None,
        contract_count=len(rows),
        total_chain_oi=total_oi,
        median_strike_oi=median_oi,
        total_friday_gex=total_friday_gex,
        friday_gex_pressure_pct=pressure,
        adv_dollar=adv_dollar,
        call_wall=call_wall,
        put_wall=put_wall,
        max_pain=_max_pain(rows) if has_data else None,
        put_call_oi_ratio=pc_ratio,
        pinning_score=score,
        verdict=_verdict(score),
        reasons=reasons,
        suggested_short_call=suggested_short_call,
        suggested_short_put=suggested_short_put,
        breakeven_low=spot - em if em else None,
        breakeven_high=spot + em if em else None,
    )
