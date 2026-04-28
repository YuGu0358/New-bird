"""IV Surface — strike x expiry IV grid + per-expiry term-structure summaries.

Pure compute, no I/O. Walls and squeeze tell you *where* and *how concentrated*
positioning is. The IV surface tells you *how the market prices uncertainty
across strikes and expiries*. A flat IV across all DTEs hints at no
calendar-spread edge; a steep front-month skew vs. flat back-month suggests
upcoming news; a high near-the-money IV at a single expiry signals event
positioning. Surfacing the raw grid gives the UI everything it needs to render
heatmaps, smile snapshots, and term-structure plots without re-deriving from
option-chain rows.

This is the data layer the heatmap UI sits on. It is intentionally NOT a SABR
or Heston fit — that's Phase 5. Here we just expose the cleaned grid.

Per (expiry, strike), we prefer the call's IV; we fall back to the put's IV
when the call IV is missing or unusable. A "usable IV" is non-None, strictly
positive, and not NaN.

Per expiry we also surface:
- ``atm_iv``: IV at the strike closest to spot (call preferred via the grid).
- ``skew_pct``: 25-delta put IV minus 25-delta call IV approximation. We pick
  the call whose delta is closest to +0.25 and the put whose delta is closest
  to -0.25; if either is missing the skew is None. Positive skew = put skew =
  downside is more expensive (typical convention).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from core.options_chain.gex import OptionContract

__all__ = [
    "IVSurface",
    "IVSurfaceExpiry",
    "IVSurfacePoint",
    "build_iv_surface",
]


@dataclass
class IVSurfacePoint:
    strike: float
    iv: float
    moneyness: float
    open_interest: int
    has_call: bool
    has_put: bool


@dataclass
class IVSurfaceExpiry:
    expiry: date
    dte: int
    atm_iv: float | None
    skew_pct: float | None
    points: list[IVSurfacePoint] = field(default_factory=list)


@dataclass
class IVSurface:
    ticker: str
    spot: float
    expiries: list[IVSurfaceExpiry] = field(default_factory=list)
    strikes: list[float] = field(default_factory=list)
    as_of: date = field(default_factory=date.today)


def _is_usable_iv(iv: float | None) -> bool:
    """iv is not None, > 0, not NaN."""
    if iv is None:
        return False
    if iv != iv:  # NaN check
        return False
    return iv > 0


def _pick_iv_for_grid(call: OptionContract | None, put: OptionContract | None) -> float | None:
    """Call IV preferred; fall back to put IV when call IV is unusable."""
    if call is not None and _is_usable_iv(call.iv):
        return float(call.iv)  # type: ignore[arg-type]
    if put is not None and _is_usable_iv(put.iv):
        return float(put.iv)  # type: ignore[arg-type]
    return None


def _closest_delta_iv(
    contracts: Iterable[OptionContract],
    *,
    target_delta: float,
    side: str,
) -> float | None:
    """IV of the contract on `side` whose delta is closest to `target_delta`.

    Only considers rows where delta is not None and IV is usable. Returns None
    if no such row exists for the side.
    """
    best: OptionContract | None = None
    best_dist = math.inf
    for c in contracts:
        if c.option_type.upper() != side:
            continue
        if c.delta is None:
            continue
        if not _is_usable_iv(c.iv):
            continue
        dist = abs(c.delta - target_delta)
        if dist < best_dist:
            best_dist = dist
            best = c
    if best is None or best.iv is None:
        return None
    return float(best.iv)


def build_iv_surface(
    *,
    ticker: str,
    spot: float,
    contracts: list[OptionContract],
    today: date | None = None,
) -> IVSurface:
    """Build the strike x expiry IV grid + per-expiry term-structure summary.

    Args:
        ticker: Underlying symbol; echoed verbatim into the response.
        spot: Underlying spot price; must be > 0 for moneyness math to be
            meaningful, but we do not raise — we trust the service layer.
        contracts: Full option chain (already merged across expiries). Empty
            input yields an IVSurface with empty `expiries` / `strikes` lists;
            we never crash.
        today: Reference date for DTE math. Defaults to ``date.today()``.

    Returns:
        IVSurface with expiries sorted ascending and strikes the union of every
        strike that has at least one usable IVSurfacePoint anywhere in the
        surface, sorted ascending.
    """
    as_of = today if today is not None else date.today()

    if not contracts:
        return IVSurface(
            ticker=ticker,
            spot=spot,
            expiries=[],
            strikes=[],
            as_of=as_of,
        )

    # Group contracts by (expiry, strike, side) so we can pair calls/puts.
    by_expiry: dict[date, dict[float, dict[str, OptionContract]]] = {}
    for c in contracts:
        side = c.option_type.upper()
        if side not in ("C", "P"):
            continue
        strike_map = by_expiry.setdefault(c.expiry, {})
        side_map = strike_map.setdefault(c.strike, {})
        # If duplicates exist, last one wins — yfinance shouldn't emit them
        # but be defensive.
        side_map[side] = c

    # Per-expiry contracts list (used for delta lookups for skew).
    contracts_by_expiry: dict[date, list[OptionContract]] = {}
    for c in contracts:
        contracts_by_expiry.setdefault(c.expiry, []).append(c)

    expiry_objs: list[IVSurfaceExpiry] = []
    all_strikes: set[float] = set()

    for exp in sorted(by_expiry.keys()):
        strike_map = by_expiry[exp]
        points: list[IVSurfacePoint] = []
        for strike in sorted(strike_map.keys()):
            sides = strike_map[strike]
            call = sides.get("C")
            put = sides.get("P")
            iv = _pick_iv_for_grid(call, put)
            if iv is None:
                continue
            call_oi = (call.open_interest or 0) if call is not None else 0
            put_oi = (put.open_interest or 0) if put is not None else 0
            moneyness = (strike - spot) / spot if spot else 0.0
            points.append(
                IVSurfacePoint(
                    strike=strike,
                    iv=iv,
                    moneyness=moneyness,
                    open_interest=max(call_oi, put_oi),
                    has_call=call is not None,
                    has_put=put is not None,
                )
            )

        # ATM IV: point whose strike is closest to spot. Tie-break: lower strike.
        atm_iv: float | None = None
        if points:
            best = min(
                points,
                key=lambda p: (abs(p.strike - spot), p.strike),
            )
            atm_iv = best.iv

        # 25-delta skew: needs both 25-delta call IV and -25-delta put IV.
        exp_contracts = contracts_by_expiry.get(exp, [])
        call25 = _closest_delta_iv(exp_contracts, target_delta=0.25, side="C")
        put25 = _closest_delta_iv(exp_contracts, target_delta=-0.25, side="P")
        skew_pct: float | None
        if call25 is not None and put25 is not None:
            skew_pct = put25 - call25
        else:
            skew_pct = None

        dte = max((exp - as_of).days, 0)

        expiry_objs.append(
            IVSurfaceExpiry(
                expiry=exp,
                dte=dte,
                atm_iv=atm_iv,
                skew_pct=skew_pct,
                points=points,
            )
        )
        for p in points:
            all_strikes.add(p.strike)

    return IVSurface(
        ticker=ticker,
        spot=spot,
        expiries=expiry_objs,
        strikes=sorted(all_strikes),
        as_of=as_of,
    )
