"""Per-expiry OI focus — drill-in for one expiry.

Inputs: full chain (`OptionContract` rows), spot, target expiry date.
Outputs: ExpiryFocus — ATM IV, 1σ expected move, top call/put OI strikes,
put/call OI ratio, max pain.

This is the data a 0DTE / weekly-credit-spread / iron-condor trader scans
when deciding "which strikes are heaviest, where will it likely pin, what's
the implied range?" — strategy-agnostic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from core.options_chain.gex import OptionContract


@dataclass
class StrikeOI:
    strike: float
    open_interest: int
    volume: int
    volume_oi_ratio: float | None
    iv: float | None
    delta: float | None
    distance_pct: float


@dataclass
class ExpiryFocus:
    ticker: str
    expiry: str  # ISO date
    dte: int
    spot: float
    atm_iv: float | None
    expected_move: float | None
    expected_low: float | None
    expected_high: float | None
    max_pain: float | None
    total_call_oi: int
    total_put_oi: int
    put_call_oi_ratio: float | None
    top_call_strikes: list[StrikeOI] = field(default_factory=list)
    top_put_strikes: list[StrikeOI] = field(default_factory=list)


def _atm_iv(rows: list[OptionContract], spot: float) -> float | None:
    """Closest-to-spot strike's IV (avg of call+put when both exist)."""
    if not rows or spot <= 0:
        return None
    nearest_strike = min({r.strike for r in rows}, key=lambda s: abs(s - spot))
    same_strike = [r for r in rows if r.strike == nearest_strike and r.iv is not None]
    if not same_strike:
        return None
    ivs = [r.iv for r in same_strike if r.iv]
    return sum(ivs) / len(ivs) if ivs else None


def _expected_move(spot: float, atm_iv: float, dte_days: int) -> float:
    """1-σ price move to expiry. Floors DTE at 1 day for intraday stability."""
    t_yrs = max(dte_days / 365.0, 1 / 365.0)
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


def _to_strike_oi(row: OptionContract, spot: float) -> StrikeOI:
    oi = int(row.open_interest or 0)
    vol = int(row.volume or 0)
    vol_oi = (vol / oi) if oi > 0 else None
    return StrikeOI(
        strike=row.strike,
        open_interest=oi,
        volume=vol,
        volume_oi_ratio=vol_oi,
        iv=row.iv,
        delta=row.delta,
        distance_pct=((row.strike - spot) / spot * 100.0) if spot > 0 else 0.0,
    )


def focus_expiry(
    *,
    ticker: str,
    spot: float,
    contracts: list[OptionContract],
    expiry: date,
    today: date | None = None,
    top_n: int = 5,
) -> ExpiryFocus | None:
    """Build the OI-focus payload for one (ticker, expiry).

    Returns None if no contracts match the requested expiry.
    """
    rows = [c for c in contracts if c.expiry == expiry]
    if not rows or spot <= 0:
        return None

    today = today or date.today()
    dte = max((expiry - today).days, 0)

    atm_iv = _atm_iv(rows, spot)
    em = _expected_move(spot, atm_iv, dte) if atm_iv else None

    calls = [r for r in rows if r.option_type.upper() == "C"]
    puts = [r for r in rows if r.option_type.upper() == "P"]
    total_call_oi = sum(int(r.open_interest or 0) for r in calls)
    total_put_oi = sum(int(r.open_interest or 0) for r in puts)
    pc_ratio = (total_put_oi / total_call_oi) if total_call_oi > 0 else None

    # Top call strikes ABOVE spot by OI (resistance)
    calls_above = sorted(
        [r for r in calls if r.strike > spot],
        key=lambda r: -(int(r.open_interest or 0)),
    )
    # Top put strikes BELOW spot by OI (support)
    puts_below = sorted(
        [r for r in puts if r.strike < spot],
        key=lambda r: -(int(r.open_interest or 0)),
    )

    return ExpiryFocus(
        ticker=ticker.upper(),
        expiry=expiry.isoformat(),
        dte=dte,
        spot=spot,
        atm_iv=atm_iv,
        expected_move=em,
        expected_low=spot - em if em else None,
        expected_high=spot + em if em else None,
        max_pain=_max_pain(rows),
        total_call_oi=total_call_oi,
        total_put_oi=total_put_oi,
        put_call_oi_ratio=pc_ratio,
        top_call_strikes=[_to_strike_oi(r, spot) for r in calls_above[:top_n]],
        top_put_strikes=[_to_strike_oi(r, spot) for r in puts_below[:top_n]],
    )
