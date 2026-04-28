"""Fixed 55-name screener universe — 5 large/mid caps per GICS sector.

The list intentionally hard-codes well-known US tickers so the screener
remains stable across releases (no S&P 500 reconstitution drift, no
yfinance label changes). Sector strings match
`core/sector_rotation/universe.py` so cross-page filtering stays
consistent.

Order: by GICS sector, then by descending market cap at time of authoring.
This is the canonical iteration order for the API response when no sort
is requested.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenerUniverseEntry:
    symbol: str
    sector: str  # human-readable GICS sector (matches sector_rotation universe)


SCREENER_UNIVERSE: tuple[ScreenerUniverseEntry, ...] = (
    # Technology
    ScreenerUniverseEntry(symbol="AAPL", sector="Technology"),
    ScreenerUniverseEntry(symbol="MSFT", sector="Technology"),
    ScreenerUniverseEntry(symbol="NVDA", sector="Technology"),
    ScreenerUniverseEntry(symbol="ORCL", sector="Technology"),
    ScreenerUniverseEntry(symbol="AVGO", sector="Technology"),
    # Financials
    ScreenerUniverseEntry(symbol="JPM", sector="Financials"),
    ScreenerUniverseEntry(symbol="BAC", sector="Financials"),
    ScreenerUniverseEntry(symbol="WFC", sector="Financials"),
    ScreenerUniverseEntry(symbol="GS", sector="Financials"),
    ScreenerUniverseEntry(symbol="V", sector="Financials"),
    # Health Care
    ScreenerUniverseEntry(symbol="UNH", sector="Health Care"),
    ScreenerUniverseEntry(symbol="JNJ", sector="Health Care"),
    ScreenerUniverseEntry(symbol="LLY", sector="Health Care"),
    ScreenerUniverseEntry(symbol="PFE", sector="Health Care"),
    ScreenerUniverseEntry(symbol="MRK", sector="Health Care"),
    # Consumer Discretionary
    ScreenerUniverseEntry(symbol="AMZN", sector="Consumer Discretionary"),
    ScreenerUniverseEntry(symbol="TSLA", sector="Consumer Discretionary"),
    ScreenerUniverseEntry(symbol="HD", sector="Consumer Discretionary"),
    ScreenerUniverseEntry(symbol="MCD", sector="Consumer Discretionary"),
    ScreenerUniverseEntry(symbol="NKE", sector="Consumer Discretionary"),
    # Consumer Staples
    ScreenerUniverseEntry(symbol="PG", sector="Consumer Staples"),
    ScreenerUniverseEntry(symbol="KO", sector="Consumer Staples"),
    ScreenerUniverseEntry(symbol="PEP", sector="Consumer Staples"),
    ScreenerUniverseEntry(symbol="COST", sector="Consumer Staples"),
    ScreenerUniverseEntry(symbol="WMT", sector="Consumer Staples"),
    # Energy
    ScreenerUniverseEntry(symbol="XOM", sector="Energy"),
    ScreenerUniverseEntry(symbol="CVX", sector="Energy"),
    ScreenerUniverseEntry(symbol="COP", sector="Energy"),
    ScreenerUniverseEntry(symbol="SLB", sector="Energy"),
    ScreenerUniverseEntry(symbol="EOG", sector="Energy"),
    # Industrials
    ScreenerUniverseEntry(symbol="GE", sector="Industrials"),
    ScreenerUniverseEntry(symbol="BA", sector="Industrials"),
    ScreenerUniverseEntry(symbol="CAT", sector="Industrials"),
    ScreenerUniverseEntry(symbol="UNP", sector="Industrials"),
    ScreenerUniverseEntry(symbol="HON", sector="Industrials"),
    # Materials
    ScreenerUniverseEntry(symbol="LIN", sector="Materials"),
    ScreenerUniverseEntry(symbol="SHW", sector="Materials"),
    ScreenerUniverseEntry(symbol="FCX", sector="Materials"),
    ScreenerUniverseEntry(symbol="NUE", sector="Materials"),
    ScreenerUniverseEntry(symbol="APD", sector="Materials"),
    # Utilities
    ScreenerUniverseEntry(symbol="NEE", sector="Utilities"),
    ScreenerUniverseEntry(symbol="DUK", sector="Utilities"),
    ScreenerUniverseEntry(symbol="SO", sector="Utilities"),
    ScreenerUniverseEntry(symbol="AEP", sector="Utilities"),
    ScreenerUniverseEntry(symbol="EXC", sector="Utilities"),
    # Real Estate
    ScreenerUniverseEntry(symbol="PLD", sector="Real Estate"),
    ScreenerUniverseEntry(symbol="AMT", sector="Real Estate"),
    ScreenerUniverseEntry(symbol="EQIX", sector="Real Estate"),
    ScreenerUniverseEntry(symbol="CCI", sector="Real Estate"),
    ScreenerUniverseEntry(symbol="PSA", sector="Real Estate"),
    # Communication Services
    ScreenerUniverseEntry(symbol="GOOGL", sector="Communication Services"),
    ScreenerUniverseEntry(symbol="META", sector="Communication Services"),
    ScreenerUniverseEntry(symbol="NFLX", sector="Communication Services"),
    ScreenerUniverseEntry(symbol="DIS", sector="Communication Services"),
    ScreenerUniverseEntry(symbol="T", sector="Communication Services"),
)
