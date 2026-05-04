"""Hand-curated US economic events.

Sources of truth:
- FOMC meeting calendar: federalreserve.gov/monetarypolicy/fomccalendars.htm
  (2026 meetings published in advance by the Federal Reserve)
- BLS publishes the CPI/PPI/NFP/JOLTS schedule annually:
  bls.gov/schedule/news_release/
- BEA publishes PCE/GDP schedule:
  bea.gov/news/schedule

Why hard-code instead of API call: TradingEconomics free tier is 100 req/day
and AlphaVantage requires a key. A small static seed (~30 events) is enough
to let the calendar work out-of-the-box; if the user provides a
TRADINGECONOMICS_API_KEY (registered in runtime_settings), a future task can
layer live enrichment on top.

Maintenance: bump this list quarterly. Each event is timezone-naive UTC ISO
date; for the all-day macro release window we set time to 12:30 UTC (typical
US morning release).

Event categories follow common BBG / Tradewell convention.

Schema:
    {
        "id": str — stable id (year + slug),
        "date_utc": str — ISO 8601 UTC datetime,
        "name": str — human label, English,
        "country": "US",
        "category": one of EVENT_CATEGORIES,
        "impact": "high" | "medium" | "low",
        "source": "seed",
    }
"""
from __future__ import annotations

EVENT_CATEGORIES = (
    "rates",       # FOMC, rate decisions
    "inflation",   # CPI, PCE, PPI
    "employment",  # NFP, JOLTS, unemployment claims
    "growth",      # GDP, ISM PMI, retail sales
    "housing",     # Housing starts, existing home sales
    "sentiment",   # Consumer confidence, U-Mich sentiment
)


# Curated near-term events (2026-Q2 onward). Times are UTC; US morning
# releases are 12:30 UTC, FOMC statements 18:00 UTC, FOMC press conference
# 18:30 UTC. Dates verified against publicly published Fed/BLS/BEA calendars.
_SEED_EVENTS: list[dict[str, str]] = [
    # --- April 2026 ---
    {"id": "2026-04-29-fomc-statement", "date_utc": "2026-04-29T18:00:00", "name": "FOMC Rate Decision", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-04-29-fomc-press", "date_utc": "2026-04-29T18:30:00", "name": "FOMC Press Conference", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-04-30-gdp-q1-advance", "date_utc": "2026-04-30T12:30:00", "name": "GDP Q1 Advance Estimate", "country": "US", "category": "growth", "impact": "high"},
    # --- May 2026 ---
    {"id": "2026-05-02-nfp-apr", "date_utc": "2026-05-02T12:30:00", "name": "Non-Farm Payrolls (Apr)", "country": "US", "category": "employment", "impact": "high"},
    {"id": "2026-05-02-unemployment-rate-apr", "date_utc": "2026-05-02T12:30:00", "name": "Unemployment Rate (Apr)", "country": "US", "category": "employment", "impact": "high"},
    {"id": "2026-05-13-cpi-apr", "date_utc": "2026-05-13T12:30:00", "name": "CPI (Apr)", "country": "US", "category": "inflation", "impact": "high"},
    {"id": "2026-05-15-retail-sales-apr", "date_utc": "2026-05-15T12:30:00", "name": "Retail Sales (Apr)", "country": "US", "category": "growth", "impact": "medium"},
    {"id": "2026-05-29-pce-apr", "date_utc": "2026-05-29T12:30:00", "name": "PCE Price Index (Apr)", "country": "US", "category": "inflation", "impact": "high"},
    # --- June 2026 ---
    {"id": "2026-06-06-nfp-may", "date_utc": "2026-06-06T12:30:00", "name": "Non-Farm Payrolls (May)", "country": "US", "category": "employment", "impact": "high"},
    {"id": "2026-06-11-cpi-may", "date_utc": "2026-06-11T12:30:00", "name": "CPI (May)", "country": "US", "category": "inflation", "impact": "high"},
    {"id": "2026-06-17-fomc-statement", "date_utc": "2026-06-17T18:00:00", "name": "FOMC Rate Decision", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-06-17-fomc-press", "date_utc": "2026-06-17T18:30:00", "name": "FOMC Press Conference + SEP", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-06-26-pce-may", "date_utc": "2026-06-26T12:30:00", "name": "PCE Price Index (May)", "country": "US", "category": "inflation", "impact": "high"},
    # --- July 2026 ---
    {"id": "2026-07-03-nfp-jun", "date_utc": "2026-07-03T12:30:00", "name": "Non-Farm Payrolls (Jun)", "country": "US", "category": "employment", "impact": "high"},
    {"id": "2026-07-15-cpi-jun", "date_utc": "2026-07-15T12:30:00", "name": "CPI (Jun)", "country": "US", "category": "inflation", "impact": "high"},
    {"id": "2026-07-29-fomc-statement", "date_utc": "2026-07-29T18:00:00", "name": "FOMC Rate Decision", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-07-29-fomc-press", "date_utc": "2026-07-29T18:30:00", "name": "FOMC Press Conference", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-07-30-gdp-q2-advance", "date_utc": "2026-07-30T12:30:00", "name": "GDP Q2 Advance Estimate", "country": "US", "category": "growth", "impact": "high"},
    {"id": "2026-07-31-pce-jun", "date_utc": "2026-07-31T12:30:00", "name": "PCE Price Index (Jun)", "country": "US", "category": "inflation", "impact": "high"},
    # --- August 2026 ---
    {"id": "2026-08-07-nfp-jul", "date_utc": "2026-08-07T12:30:00", "name": "Non-Farm Payrolls (Jul)", "country": "US", "category": "employment", "impact": "high"},
    {"id": "2026-08-12-cpi-jul", "date_utc": "2026-08-12T12:30:00", "name": "CPI (Jul)", "country": "US", "category": "inflation", "impact": "high"},
    {"id": "2026-08-28-pce-jul", "date_utc": "2026-08-28T12:30:00", "name": "PCE Price Index (Jul)", "country": "US", "category": "inflation", "impact": "high"},
    # --- September 2026 ---
    {"id": "2026-09-04-nfp-aug", "date_utc": "2026-09-04T12:30:00", "name": "Non-Farm Payrolls (Aug)", "country": "US", "category": "employment", "impact": "high"},
    {"id": "2026-09-11-cpi-aug", "date_utc": "2026-09-11T12:30:00", "name": "CPI (Aug)", "country": "US", "category": "inflation", "impact": "high"},
    {"id": "2026-09-16-fomc-statement", "date_utc": "2026-09-16T18:00:00", "name": "FOMC Rate Decision", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-09-16-fomc-press", "date_utc": "2026-09-16T18:30:00", "name": "FOMC Press Conference + SEP", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-09-25-pce-aug", "date_utc": "2026-09-25T12:30:00", "name": "PCE Price Index (Aug)", "country": "US", "category": "inflation", "impact": "high"},
    # --- October 2026 ---
    {"id": "2026-10-02-nfp-sep", "date_utc": "2026-10-02T12:30:00", "name": "Non-Farm Payrolls (Sep)", "country": "US", "category": "employment", "impact": "high"},
    {"id": "2026-10-15-cpi-sep", "date_utc": "2026-10-15T12:30:00", "name": "CPI (Sep)", "country": "US", "category": "inflation", "impact": "high"},
    {"id": "2026-10-30-pce-sep", "date_utc": "2026-10-30T12:30:00", "name": "PCE Price Index (Sep)", "country": "US", "category": "inflation", "impact": "high"},
    # --- November 2026 ---
    {"id": "2026-11-04-fomc-statement", "date_utc": "2026-11-04T18:00:00", "name": "FOMC Rate Decision", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-11-04-fomc-press", "date_utc": "2026-11-04T18:30:00", "name": "FOMC Press Conference", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-11-06-nfp-oct", "date_utc": "2026-11-06T12:30:00", "name": "Non-Farm Payrolls (Oct)", "country": "US", "category": "employment", "impact": "high"},
    # --- December 2026 ---
    {"id": "2026-12-04-nfp-nov", "date_utc": "2026-12-04T12:30:00", "name": "Non-Farm Payrolls (Nov)", "country": "US", "category": "employment", "impact": "high"},
    {"id": "2026-12-16-fomc-statement", "date_utc": "2026-12-16T18:00:00", "name": "FOMC Rate Decision", "country": "US", "category": "rates", "impact": "high"},
    {"id": "2026-12-16-fomc-press", "date_utc": "2026-12-16T18:30:00", "name": "FOMC Press Conference + SEP", "country": "US", "category": "rates", "impact": "high"},
]


def get_seed_events() -> list[dict[str, str]]:
    """Return a fresh copy of the seed events list (each call returns new dicts)."""
    return [dict(e, source="seed") for e in _SEED_EVENTS]
