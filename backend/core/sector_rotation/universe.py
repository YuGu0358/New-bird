"""The 11 GICS sector SPDRs — fixed universe for the rotation matrix.

These are the canonical Select Sector SPDR ETFs. Fixing the list here keeps
the rotation view stable across releases (no drift if the State Street site
relabels something) and is small enough that we don't need a DB table for it.

Order matches GICS sector-ID convention so tile layout is deterministic
regardless of how the upstream data fetcher returns rows.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SectorETF:
    symbol: str
    sector: str  # human-readable GICS sector


SECTOR_ETFS: tuple[SectorETF, ...] = (
    SectorETF(symbol="XLK", sector="Technology"),
    SectorETF(symbol="XLF", sector="Financials"),
    SectorETF(symbol="XLV", sector="Health Care"),
    SectorETF(symbol="XLY", sector="Consumer Discretionary"),
    SectorETF(symbol="XLP", sector="Consumer Staples"),
    SectorETF(symbol="XLE", sector="Energy"),
    SectorETF(symbol="XLI", sector="Industrials"),
    SectorETF(symbol="XLB", sector="Materials"),
    SectorETF(symbol="XLU", sector="Utilities"),
    SectorETF(symbol="XLRE", sector="Real Estate"),
    SectorETF(symbol="XLC", sector="Communication Services"),
)
