"""Tests for the Phase 4 research router endpoints.

All upstream services are mocked at the module boundary — these tests
never call OpenAI, yfinance, SEC EDGAR, or the real DCF engine.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import (
    company_profile_service,
    research_service,
    valuation_service,
)
from core.agents import LLMRouterUnavailableError, ResearchAnalyzerParseError
from core.agents.research_schemas import (
    EarningsReview,
    FilingHighlight,
    GuidanceChange,
    IdeaShortlistItem,
    MarketResearchReport,
    PeerComps,
    PeerRow,
    VarianceRow,
)


def _sample_market_research_report() -> MarketResearchReport:
    """Build a minimal valid `MarketResearchReport` dataclass."""
    return MarketResearchReport(
        sector="semiconductors",
        theme="AI accelerators",
        industry_overview="Industry overview text.",
        key_drivers=("Driver 1", "Driver 2"),
        competitive_landscape="Competitive landscape text.",
        peer_comps=PeerComps(
            peers=(
                PeerRow(
                    symbol="NVDA",
                    name="NVIDIA",
                    market_cap=3.0e12,
                    pe_ratio=55.0,
                    ev_ebitda=40.0,
                    ps_ratio=20.0,
                    revenue_growth_yoy=0.5,
                    notes="Leader",
                ),
            ),
            median_pe=55.0,
            median_ev_ebitda=40.0,
            commentary="Sector trades at a premium.",
        ),
        ideas_shortlist=(
            IdeaShortlistItem(
                symbol="AMD",
                thesis="MI300 ramp",
                catalyst="Q4 print",
                risk="Customer concentration",
            ),
        ),
        key_risks=("Cycle risk",),
        sector_thesis="Constructive on AI accelerators.",
    )


def _sample_earnings_review() -> EarningsReview:
    return EarningsReview(
        symbol="AAPL",
        period="FY2025 Q3",
        variance_table=(
            VarianceRow(
                metric="Revenue",
                actual=100.0,
                consensus=98.0,
                prior=95.0,
                surprise_pct=0.02,
                commentary="Beat",
            ),
        ),
        guidance_changes=(
            GuidanceChange(
                metric="FY revenue",
                prior_guidance="400B",
                new_guidance="410B",
                direction="raised",
            ),
        ),
        filing_highlights=(
            FilingHighlight(
                accession_number="0000320193-25-000001",
                form_type="10-Q",
                excerpt="Quoted excerpt.",
                relevance="Why it matters.",
            ),
        ),
        note_draft="Drafted analyst note.",
        key_takeaways=("Takeaway 1",),
        follow_ups=("Follow-up 1",),
    )


class MarketResearchRouterTests(unittest.TestCase):
    def test_post_market_happy_path(self) -> None:
        report = _sample_market_research_report()
        with patch.object(
            research_service,
            "run_market_research",
            new=AsyncMock(return_value=report),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/research/market",
                    json={
                        "sector": "semiconductors",
                        "theme": "AI accelerators",
                        "peer_count": 5,
                    },
                )

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["sector"], "semiconductors")
        self.assertEqual(body["theme"], "AI accelerators")
        self.assertEqual(len(body["peer_comps"]["peers"]), 1)
        self.assertEqual(body["peer_comps"]["peers"][0]["symbol"], "NVDA")
        self.assertEqual(body["ideas_shortlist"][0]["symbol"], "AMD")

    def test_post_market_llm_unavailable_returns_503(self) -> None:
        with patch.object(
            research_service,
            "run_market_research",
            new=AsyncMock(side_effect=LLMRouterUnavailableError("no api key")),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/research/market",
                    json={"sector": "semiconductors"},
                )
        self.assertEqual(resp.status_code, 503)
        self.assertIn("no api key", resp.json()["detail"])

    def test_post_market_validates_peer_count(self) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/api/research/market",
                json={"sector": "semiconductors", "peer_count": 25},
            )
        self.assertEqual(resp.status_code, 422)


class EarningsReviewRouterTests(unittest.TestCase):
    def test_post_earnings_happy_path(self) -> None:
        review = _sample_earnings_review()
        with patch.object(
            research_service,
            "run_earnings_review",
            new=AsyncMock(return_value=review),
        ):
            with TestClient(app) as client:
                resp = client.post("/api/research/earnings/AAPL", json={})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["symbol"], "AAPL")
        self.assertEqual(body["period"], "FY2025 Q3")
        self.assertEqual(len(body["variance_table"]), 1)
        self.assertEqual(body["variance_table"][0]["metric"], "Revenue")
        self.assertEqual(body["guidance_changes"][0]["direction"], "raised")

    def test_post_earnings_parse_error_returns_502(self) -> None:
        with patch.object(
            research_service,
            "run_earnings_review",
            new=AsyncMock(
                side_effect=ResearchAnalyzerParseError("malformed JSON")
            ),
        ):
            with TestClient(app) as client:
                resp = client.post("/api/research/earnings/AAPL", json={})

        self.assertEqual(resp.status_code, 502)
        self.assertIn("malformed JSON", resp.json()["detail"])


class CompsRouterTests(unittest.TestCase):
    def test_get_comps_happy_path(self) -> None:
        # Subject's profile (AAPL) and per-peer profiles are all mocked. We
        # use sector "Technology" so the static fallback peers in the
        # research service are accepted as same-sector peers.
        async def _fake_profile(symbol: str, **_: object) -> dict[str, object]:
            return {
                "symbol": symbol,
                "company_name": f"{symbol} Inc",
                "sector": "Technology",
                "industry": "Software",
                "market_cap": 1.0e12,
                "pe_ratio": 30.0,
            }

        with patch.object(
            company_profile_service,
            "get_company_profile",
            new=AsyncMock(side_effect=_fake_profile),
        ):
            with TestClient(app) as client:
                resp = client.get("/api/research/comps/AAPL?n=8")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["symbol"], "AAPL")
        self.assertLessEqual(len(body["peers"]), 8)
        self.assertGreater(len(body["peers"]), 0)
        self.assertEqual(
            body["commentary"],
            "Deterministic peer comps from sector classification.",
        )
        # Subject itself must not appear in its own peer list.
        peer_symbols = {p["symbol"] for p in body["peers"]}
        self.assertNotIn("AAPL", peer_symbols)

    def test_get_comps_unknown_symbol_returns_404(self) -> None:
        with patch.object(
            company_profile_service,
            "get_company_profile",
            new=AsyncMock(side_effect=LookupError("no such ticker")),
        ):
            with TestClient(app) as client:
                resp = client.get("/api/research/comps/UNKNOWNX")

        self.assertEqual(resp.status_code, 404)


class DcfRouterTests(unittest.TestCase):
    def test_get_research_dcf_happy_path(self) -> None:
        fake_payload = {
            "inputs": {
                "fcfe0": 5.0,
                "growth_stage1": 0.08,
                "growth_terminal": 0.025,
                "discount_rate": 0.09,
                "years_stage1": 7,
                "shares_out": None,
            },
            "fair_value_per_share": 100.0,
            "fair_low": 90.0,
            "fair_high": 110.0,
            "breakdown": {"pv_stage1": 30.0, "pv_terminal": 70.0},
            "grid": [
                {"delta_growth": 0.0, "delta_discount": 0.0, "fair_value": 100.0},
            ],
            "generated_at": datetime.now(timezone.utc),
        }

        with patch.object(
            valuation_service, "compute_dcf", return_value=fake_payload
        ):
            with TestClient(app) as client:
                resp = client.get("/api/research/dcf/AAPL")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["symbol"], "AAPL")
        self.assertEqual(body["fair_value_per_share"], 100.0)
        self.assertEqual(body["source"], "internal valuation engine")
        self.assertEqual(len(body["grid"]), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
