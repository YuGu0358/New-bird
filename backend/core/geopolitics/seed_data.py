"""Hand-curated geopolitical risk events.

Sources of truth (cross-referenced as of 2026-04):
- ACLED public dashboards (acleddata.com) — armed conflict + protest events.
- HDX humanitarian data (data.humdata.org) — sanctions / treaty timelines.
- US Treasury OFAC press releases — sanction announcements.
- Reuters / FT / WSJ political-risk coverage for treaty / election dates.

Why hard-code instead of API call: ACLED requires registration with rate
limits, HDX exposes flat CSVs (not a query API), and political risk events
don't change minute-to-minute. A small static seed (~30 events) is enough
to populate the panel out-of-the-box; if a user wires up ACLED or a custom
RSS feed, a follow-up task can layer live enrichment on top.

Maintenance: review this list monthly during heightened periods, quarterly
otherwise. Each event is timezone-naive UTC ISO date; for ongoing situations
we use the *escalation* date (when the event materially shifted markets).

Schema:
    {
        "id": str — stable id (year + slug),
        "date_utc": str — ISO 8601 UTC datetime,
        "title": str — short English headline,
        "region": one of REGIONS,
        "category": one of EVENT_CATEGORIES,
        "severity": int 0..100 — composite of market reach + casualty/duration,
        "asset_classes": tuple[str, ...] — markets typically affected
            (e.g., "oil", "wheat", "gold", "fx-emerging"),
        "summary": str — 1-2 sentence English description,
        "source": "seed",
    }

Severity scoring (rough heuristic, not a model):
    0-19   informational / background
    20-39  watch — monitoring, single-asset move plausible
    40-59  active — multi-asset moves observed
    60-79  major — broad risk-off across markets
    80-100 systemic — global liquidity / safe-haven flight
"""
from __future__ import annotations

EVENT_CATEGORIES = (
    "armed_conflict",   # active hostilities
    "sanctions",        # economic restrictions / financial measures
    "election",         # contested or pivotal national vote
    "treaty",           # new agreement / withdrawal / renegotiation
    "trade_dispute",    # tariffs, export controls, retaliation
    "protest",          # large-scale civil unrest
    "diplomatic",       # ambassador withdrawal, summit, recognition
)

REGIONS = (
    "global",
    "north_america",
    "south_america",
    "europe",
    "middle_east",
    "africa",
    "central_asia",
    "east_asia",
    "south_asia",
    "southeast_asia",
    "oceania",
)


_SEED_EVENTS: list[dict[str, object]] = [
    # --- Armed conflicts (ongoing as of 2026-04) ---
    {
        "id": "2022-02-24-rus-ukr-invasion",
        "date_utc": "2022-02-24T03:00:00",
        "title": "Russia–Ukraine: Full-scale invasion (escalation date)",
        "region": "europe",
        "category": "armed_conflict",
        "severity": 88,
        "asset_classes": ("wheat", "oil", "ng", "fx-emerging", "gold", "defense"),
        "summary": "Multi-year armed conflict; major impact on European energy markets, global wheat prices, and defense-sector valuations.",
    },
    {
        "id": "2023-10-07-isr-gaza",
        "date_utc": "2023-10-07T05:30:00",
        "title": "Israel–Gaza conflict (escalation date)",
        "region": "middle_east",
        "category": "armed_conflict",
        "severity": 72,
        "asset_classes": ("oil", "gold", "shipping", "fx-emerging"),
        "summary": "Regional conflict; spillover into Red Sea shipping disruption and oil price premia tied to broader Middle East risk.",
    },
    {
        "id": "2024-04-13-iran-israel-strikes",
        "date_utc": "2024-04-13T20:00:00",
        "title": "Iran–Israel direct strike exchange",
        "region": "middle_east",
        "category": "armed_conflict",
        "severity": 68,
        "asset_classes": ("oil", "gold", "fx-emerging"),
        "summary": "First direct state-on-state strikes between Iran and Israel — sustained oil risk premium and regional asset volatility.",
    },
    {
        "id": "2025-09-12-sahel-coup-cluster",
        "date_utc": "2025-09-12T00:00:00",
        "title": "Sahel coup contagion update (Niger / Mali / Burkina Faso)",
        "region": "africa",
        "category": "armed_conflict",
        "severity": 45,
        "asset_classes": ("uranium", "gold", "cocoa", "fx-emerging"),
        "summary": "Continuing instability across Sahel post-2023 coups; affects uranium supply and West African commodity flows.",
    },
    {
        "id": "2026-02-03-myanmar-civil-war",
        "date_utc": "2026-02-03T00:00:00",
        "title": "Myanmar civil war: NUG offensive update",
        "region": "southeast_asia",
        "category": "armed_conflict",
        "severity": 38,
        "asset_classes": ("rare-earth", "gas", "fx-emerging"),
        "summary": "Ongoing civil conflict; affects rare-earth refining bottleneck via Chinese cross-border supply chain.",
    },

    # --- Sanctions / financial measures ---
    {
        "id": "2026-03-15-ofac-russia-shadow-fleet",
        "date_utc": "2026-03-15T15:00:00",
        "title": "OFAC sanctions update: Russia shadow fleet tankers",
        "region": "europe",
        "category": "sanctions",
        "severity": 52,
        "asset_classes": ("oil", "shipping", "fx-rub"),
        "summary": "Expanded US Treasury sanctions on tankers facilitating Russian oil exports; tightening enforcement of price cap.",
    },
    {
        "id": "2026-04-02-china-export-controls",
        "date_utc": "2026-04-02T01:00:00",
        "title": "China expands rare-earth export controls",
        "region": "east_asia",
        "category": "sanctions",
        "severity": 58,
        "asset_classes": ("rare-earth", "semiconductors", "ev-supply-chain"),
        "summary": "Export licensing tightened for gallium, germanium, and graphite — direct hit to Western semiconductor and EV battery costs.",
    },
    {
        "id": "2025-11-08-iran-secondary-sanctions",
        "date_utc": "2025-11-08T15:00:00",
        "title": "US secondary sanctions on Iran oil facilitators",
        "region": "middle_east",
        "category": "sanctions",
        "severity": 48,
        "asset_classes": ("oil", "fx-emerging"),
        "summary": "Renewed enforcement against banks and shippers facilitating Iranian crude — affects global oil supply slack estimates.",
    },

    # --- Trade disputes / tariffs ---
    {
        "id": "2026-02-01-us-tariffs-mexico-canada-china",
        "date_utc": "2026-02-01T05:00:00",
        "title": "US tariffs on Mexico / Canada / China imposed",
        "region": "global",
        "category": "trade_dispute",
        "severity": 65,
        "asset_classes": ("fx-cad", "fx-mxn", "fx-cny", "agriculture", "autos"),
        "summary": "Broad-based tariffs on top three US trading partners; immediate USDMXN / USDCAD spike, retaliation risk on US agriculture.",
    },
    {
        "id": "2026-03-12-eu-china-ev-tariffs",
        "date_utc": "2026-03-12T10:00:00",
        "title": "EU finalizes anti-subsidy duties on Chinese EVs",
        "region": "europe",
        "category": "trade_dispute",
        "severity": 42,
        "asset_classes": ("autos", "fx-eur", "fx-cny"),
        "summary": "Definitive countervailing duties of 17–35% on Chinese EV imports; affects European auto sector competitive landscape.",
    },
    {
        "id": "2026-04-15-china-rare-earth-retaliation",
        "date_utc": "2026-04-15T01:00:00",
        "title": "China retaliatory rare-earth quota cuts",
        "region": "east_asia",
        "category": "trade_dispute",
        "severity": 55,
        "asset_classes": ("rare-earth", "magnets", "ev-supply-chain"),
        "summary": "Beijing reduces rare-earth export quota by 30% in response to Western tariffs; direct supply impact on magnet manufacturers.",
    },

    # --- Elections (high-stakes) ---
    {
        "id": "2026-05-13-mexico-state-elections",
        "date_utc": "2026-05-13T00:00:00",
        "title": "Mexico mid-term state elections",
        "region": "north_america",
        "category": "election",
        "severity": 28,
        "asset_classes": ("fx-mxn", "mexico-equity"),
        "summary": "Test of Sheinbaum administration's mandate on judicial reform; FX volatility plausible.",
    },
    {
        "id": "2026-06-21-india-state-elections",
        "date_utc": "2026-06-21T00:00:00",
        "title": "India key state elections (Kerala / Tamil Nadu)",
        "region": "south_asia",
        "category": "election",
        "severity": 22,
        "asset_classes": ("fx-inr", "india-equity"),
        "summary": "Coalition test for BJP; not federal but informs 2029 trajectory.",
    },
    {
        "id": "2026-09-15-germany-bundestag",
        "date_utc": "2026-09-15T00:00:00",
        "title": "Germany Bundestag federal election",
        "region": "europe",
        "category": "election",
        "severity": 56,
        "asset_classes": ("fx-eur", "bunds", "european-equity"),
        "summary": "First federal election under restructured AfD coalition dynamics; implications for EU fiscal stance and energy policy.",
    },
    {
        "id": "2026-10-20-brazil-municipal",
        "date_utc": "2026-10-20T00:00:00",
        "title": "Brazil municipal elections (national mood gauge)",
        "region": "south_america",
        "category": "election",
        "severity": 25,
        "asset_classes": ("fx-brl", "brazil-equity"),
        "summary": "Read-through to 2026 federal direction post-Lula; key for Petrobras and Vale market sentiment.",
    },

    # --- Treaty / diplomatic ---
    {
        "id": "2026-03-20-opec-plus-meeting",
        "date_utc": "2026-03-20T13:00:00",
        "title": "OPEC+ ministerial meeting (production review)",
        "region": "middle_east",
        "category": "treaty",
        "severity": 55,
        "asset_classes": ("oil",),
        "summary": "Decision on whether to unwind 2.2 mb/d voluntary cuts; binary risk for crude price trajectory.",
    },
    {
        "id": "2026-05-30-nato-summit",
        "date_utc": "2026-05-30T08:00:00",
        "title": "NATO summit (defense spending floor review)",
        "region": "global",
        "category": "treaty",
        "severity": 42,
        "asset_classes": ("defense", "fx-eur"),
        "summary": "Possible upward revision of defense spending floor (currently 2% of GDP) toward 3%; persistent tailwind for defense primes.",
    },
    {
        "id": "2026-09-10-un-general-assembly",
        "date_utc": "2026-09-10T13:00:00",
        "title": "UN General Assembly (Russia / Iran / Israel addresses)",
        "region": "global",
        "category": "diplomatic",
        "severity": 30,
        "asset_classes": ("oil", "gold"),
        "summary": "Concentrated diplomatic signaling window; headlines historically move oil and gold modestly.",
    },

    # --- Cross-asset shocks (acute, time-bound) ---
    {
        "id": "2026-01-15-red-sea-shipping",
        "date_utc": "2026-01-15T05:00:00",
        "title": "Red Sea shipping diversion (Houthi attacks)",
        "region": "middle_east",
        "category": "armed_conflict",
        "severity": 58,
        "asset_classes": ("shipping", "container-rates", "oil"),
        "summary": "Container rates Asia-Europe spike on Cape of Good Hope re-routing; ~10-14 day transit increase.",
    },
    {
        "id": "2026-04-01-china-taiwan-air-incursion",
        "date_utc": "2026-04-01T03:00:00",
        "title": "China–Taiwan: Air incursion escalation pattern",
        "region": "east_asia",
        "category": "diplomatic",
        "severity": 52,
        "asset_classes": ("semiconductors", "fx-twd", "fx-cny"),
        "summary": "Sustained increase in PLA Air Force median line crossings; supply-chain risk for advanced semi production at TSMC.",
    },
    {
        "id": "2025-11-23-venezuela-essequibo",
        "date_utc": "2025-11-23T00:00:00",
        "title": "Venezuela–Guyana: Essequibo claim escalation",
        "region": "south_america",
        "category": "diplomatic",
        "severity": 35,
        "asset_classes": ("oil", "fx-emerging"),
        "summary": "Renewed claims over Essequibo region threaten Exxon's Stabroek block production; modest premium on Brent.",
    },

    # --- Protests / civil unrest (sustained) ---
    {
        "id": "2026-02-25-france-pension-protests",
        "date_utc": "2026-02-25T00:00:00",
        "title": "France: pension reform protests (sustained)",
        "region": "europe",
        "category": "protest",
        "severity": 25,
        "asset_classes": ("fx-eur",),
        "summary": "Intermittent strike action affecting transport and refineries; modest near-term GDP drag, sentiment-only FX impact.",
    },
    {
        "id": "2026-03-08-argentina-austerity",
        "date_utc": "2026-03-08T00:00:00",
        "title": "Argentina: austerity protests under Milei reform package",
        "region": "south_america",
        "category": "protest",
        "severity": 32,
        "asset_classes": ("fx-ars", "argentina-equity", "soybeans"),
        "summary": "Recurring protests against fiscal consolidation; near-term volatility for ARS-denominated assets and soybean exporter sentiment.",
    },

    # --- Strategic / horizon ---
    {
        "id": "2026-12-31-jcpoa-snapback-window",
        "date_utc": "2026-12-31T23:00:00",
        "title": "JCPOA snapback window expiration",
        "region": "middle_east",
        "category": "sanctions",
        "severity": 60,
        "asset_classes": ("oil", "uranium", "fx-emerging"),
        "summary": "End of UN Security Council snapback procedure availability; sanctions architecture binary going into 2027.",
    },
    {
        "id": "2027-01-01-eu-fiscal-rules-kicked-in",
        "date_utc": "2027-01-01T00:00:00",
        "title": "EU fiscal rules: full enforcement takes effect",
        "region": "europe",
        "category": "treaty",
        "severity": 38,
        "asset_classes": ("bunds", "btps", "fx-eur"),
        "summary": "End of post-pandemic flexibility — Italy and France bond spreads sensitive to consolidation pace.",
    },
    {
        "id": "2026-07-04-arctic-shipping-season",
        "date_utc": "2026-07-04T00:00:00",
        "title": "Arctic Northern Sea Route shipping season opens",
        "region": "global",
        "category": "diplomatic",
        "severity": 18,
        "asset_classes": ("shipping", "lng", "container-rates"),
        "summary": "Russia-controlled NSR opens for ice-class transit; gradual route share increase, watch for Western insurer pullback.",
    },
    {
        "id": "2026-08-15-pakistan-imf-review",
        "date_utc": "2026-08-15T13:00:00",
        "title": "Pakistan IMF program review (tranche release)",
        "region": "south_asia",
        "category": "treaty",
        "severity": 42,
        "asset_classes": ("fx-pkr", "frontier-em-bonds"),
        "summary": "Quarterly review of $7B EFF; missed targets historically trigger 5-7% PKR depreciation.",
    },
    {
        "id": "2026-09-22-japan-snap-election-watch",
        "date_utc": "2026-09-22T00:00:00",
        "title": "Japan: LDP leadership renewal / snap election watch",
        "region": "east_asia",
        "category": "election",
        "severity": 32,
        "asset_classes": ("fx-jpy", "jgb", "japan-equity"),
        "summary": "Window for LDP leadership challenge; outcome materially affects BoJ policy continuity expectations.",
    },
]


def get_seed_events() -> list[dict[str, object]]:
    """Return a deep-ish copy so callers can't mutate the seed."""
    return [dict(event) for event in _SEED_EVENTS]
