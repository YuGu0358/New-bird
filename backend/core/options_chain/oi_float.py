"""OI-to-float analysis — what fraction of public float does the chain represent?

Pure compute, no I/O. The service layer feeds in the option chain (already
fetched) and the underlying's float-share count.

Two views, side by side:

1. **Notional**: every open contract = 100 shares of underlying. Sum across the
   chain gives a coarse upper bound on positioning intensity if every contract
   were exercised. Useful as a worst-case but blunt — most far-OTM contracts
   will never go ITM.

2. **Delta-adjusted**: weight each contract by ``|delta|`` before multiplying
   by the contract size. Dealers hedge by share-equivalent delta, so
   ``Σ |delta| × OI × 100`` is a closer estimate of the actual share demand
   the options book represents. Calls and puts are treated symmetrically — both
   sides represent share-equivalent dealer-hedge exposure on the float, so we
   take the absolute value of delta on the put side too.

Comparing the two highlights how skewed the chain is toward deep-OTM positions
(delta-adjusted/notional ratio is small) vs near-the-money (ratio approaches 1).

If ``float_shares`` is missing or non-positive every ``*_pct`` field is ``None``;
the share fields still compute. Pct fields are returned as fractions (e.g. 0.45
for 45%); the UI scales for display.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.options_chain.gex import CONTRACT_MULTIPLIER, OptionContract

__all__ = ["CONTRACT_MULTIPLIER", "OIFloatBreakdown", "compute_oi_float"]


@dataclass
class OIFloatBreakdown:
    total_call_oi: int
    total_put_oi: int
    # Notional view (every OI contract = 100 shares).
    notional_call_shares: int
    notional_put_shares: int
    notional_total_shares: int
    notional_call_pct: float | None  # notional_call_shares / float_shares
    notional_put_pct: float | None
    notional_total_pct: float | None
    # Delta-adjusted view (Σ |delta| × OI × 100, |delta| on both sides).
    delta_adjusted_call_shares: float
    delta_adjusted_put_shares: float
    delta_adjusted_total_shares: float
    delta_adjusted_call_pct: float | None
    delta_adjusted_put_pct: float | None
    delta_adjusted_total_pct: float | None
    # Diagnostics
    contracts_with_delta: int  # rows that contributed to the delta sum
    contracts_total: int


def _pct(shares: float, float_shares: int | None) -> float | None:
    """Fraction of float, or None if float is missing / non-positive."""
    if float_shares is None or float_shares <= 0:
        return None
    return shares / float_shares


def compute_oi_float(
    contracts: Iterable[OptionContract],
    *,
    float_shares: int | None,
) -> OIFloatBreakdown:
    """Roll the chain into notional + delta-adjusted shares relative to float.

    Args:
        contracts: Full option chain (already merged across expiries).
        float_shares: Public float count from yfinance ``floatShares``.
            ``None`` or any value ``<= 0`` is treated as missing — share
            fields still compute, every ``*_pct`` returns ``None``.

    Per-contract rules:
        - Rows with ``oi <= 0`` are skipped completely (no contribution to
          notional shares, delta-adjusted shares, or ``contracts_with_delta``;
          they still count toward ``contracts_total``).
        - Notional always contributes ``oi * CONTRACT_MULTIPLIER``.
        - Delta-adjusted contributes ``|delta| * oi * CONTRACT_MULTIPLIER``
          only when ``delta is not None``; rows with missing delta are
          excluded from the delta sum but still counted in ``contracts_total``.
        - ``contracts_with_delta`` counts only rows that actually contributed
          to the delta sum (``delta is not None`` AND ``oi > 0``).

    Returns:
        ``OIFloatBreakdown`` with totals, share counts, fractions of float,
        and diagnostics for the call/put split and chain-wide aggregate.
    """
    total_call_oi = 0
    total_put_oi = 0
    notional_call_shares = 0
    notional_put_shares = 0
    delta_adjusted_call_shares = 0.0
    delta_adjusted_put_shares = 0.0
    contracts_with_delta = 0
    contracts_total = 0

    for c in contracts:
        contracts_total += 1
        oi = c.open_interest or 0
        if oi <= 0:
            continue

        is_call = c.option_type.upper() == "C"
        notional = oi * CONTRACT_MULTIPLIER
        if is_call:
            total_call_oi += oi
            notional_call_shares += notional
        else:
            total_put_oi += oi
            notional_put_shares += notional

        if c.delta is not None:
            delta_share = abs(c.delta) * oi * CONTRACT_MULTIPLIER
            if is_call:
                delta_adjusted_call_shares += delta_share
            else:
                delta_adjusted_put_shares += delta_share
            contracts_with_delta += 1

    notional_total_shares = notional_call_shares + notional_put_shares
    delta_adjusted_total_shares = (
        delta_adjusted_call_shares + delta_adjusted_put_shares
    )

    return OIFloatBreakdown(
        total_call_oi=total_call_oi,
        total_put_oi=total_put_oi,
        notional_call_shares=notional_call_shares,
        notional_put_shares=notional_put_shares,
        notional_total_shares=notional_total_shares,
        notional_call_pct=_pct(notional_call_shares, float_shares),
        notional_put_pct=_pct(notional_put_shares, float_shares),
        notional_total_pct=_pct(notional_total_shares, float_shares),
        delta_adjusted_call_shares=delta_adjusted_call_shares,
        delta_adjusted_put_shares=delta_adjusted_put_shares,
        delta_adjusted_total_shares=delta_adjusted_total_shares,
        delta_adjusted_call_pct=_pct(delta_adjusted_call_shares, float_shares),
        delta_adjusted_put_pct=_pct(delta_adjusted_put_shares, float_shares),
        delta_adjusted_total_pct=_pct(delta_adjusted_total_shares, float_shares),
        contracts_with_delta=contracts_with_delta,
        contracts_total=contracts_total,
    )
