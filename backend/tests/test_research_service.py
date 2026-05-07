"""Tests for research_service: context builders, run_* flow, persistence.

Mirrors the `_isolate_db` fixture pattern from test_journal_service.py /
test_agents_service.py so each test runs against a fresh tmp SQLite DB.
External services (sector_rotation, company_profile, market_research,
sec_edgar) are monkeypatched per test.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.database import AsyncSessionLocal


# ---------------------------------------------------------------------------
# Fresh-DB fixture — same pattern as test_journal_service.py
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Per-test tmp DB so ResearchOutput rows don't leak across tests."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    original_engine = engine_module.engine
    db_path = tmp_path / "research.db"
    new_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", echo=False, future=True
    )
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)
    # research_service binds `AsyncSessionLocal` at import time — patch it
    # directly so no-session paths (history list / persistence without
    # caller-provided session) hit the per-test tmp DB.
    from app.services import research_service as _research_service
    monkeypatch.setattr(_research_service, "AsyncSessionLocal", new_session_factory)
    AsyncSessionLocal.configure(bind=new_engine)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    AsyncSessionLocal.configure(bind=original_engine)
    await new_engine.dispose()


# ---------------------------------------------------------------------------
# Stub upstreams shared across tests
# ---------------------------------------------------------------------------


def _stub_sector_rotation_payload() -> dict[str, Any]:
    return {
        "rows": [
            {
                "sector": "Semiconductors",
                "returns": {"1m": 0.05, "3m": 0.12, "12m": 0.45},
            },
            {
                "sector": "Healthcare",
                "returns": {"1m": -0.01, "3m": 0.03, "12m": 0.08},
            },
        ],
    }


def _stub_company_profile(symbol: str) -> dict[str, Any]:
    return {
        "company_name": f"{symbol} Inc.",
        "sector": "Semiconductors",
        "industry": "Logic chips",
        "market_cap": 1_000_000_000_000,
        "currency": "USD",
    }


def _stub_market_news(symbol: str) -> dict[str, Any]:
    return {
        "items": [
            {
                "title": f"{symbol} headline 1",
                "summary": "summary 1",
                "source": "TestWire",
                "at": "2026-05-01T00:00:00+00:00",
            },
            {
                "title": f"{symbol} headline 2",
                "summary": "summary 2",
                "source": "TestWire",
            },
        ]
    }


def _stub_recent_filings(symbol: str, limit: int = 3) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "cik": "0000000001",
        "form_types": ["10-Q", "8-K", "10-K"],
        "limit": limit,
        "filings": [
            {
                "accession_number": "0000000001-25-000001",
                "form_type": "8-K",
                "filing_date": "2026-04-30",
                "primary_doc_url": f"https://example.test/{symbol}/8-K",
            },
            {
                "accession_number": "0000000001-25-000002",
                "form_type": "10-Q",
                "filing_date": "2026-03-31",
                "primary_doc_url": f"https://example.test/{symbol}/10-Q",
            },
        ],
    }


def _stub_filing_text(text: str = "Filing body excerpt.") -> dict[str, Any]:
    return {
        "accession_number": "0000000001-25-000001",
        "cik": "1",
        "index_url": "https://example.test/index.htm",
        "browse_url": "https://example.test/browse",
        "max_chars": 5000,
        "truncated": False,
        "text": text,
    }


def _patch_market_research_upstreams(monkeypatch) -> None:
    from app.services import (
        company_profile_service,
        research_service,
        sec_edgar_service,
        sector_rotation_service,
        tavily_service,
    )

    async def fake_rotation(*, force: bool = False) -> dict[str, Any]:
        return _stub_sector_rotation_payload()

    async def fake_profile(symbol: str, *, lang: str = "en") -> dict[str, Any]:
        return _stub_company_profile(symbol)

    async def fake_news(symbol: str, *, lang: str = "en") -> dict[str, Any]:
        return _stub_market_news(symbol)

    async def fake_filings(
        symbol: str,
        form_types: tuple[str, ...] = ("10-K", "10-Q", "8-K"),
        limit: int = 20,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        return _stub_recent_filings(symbol, limit=limit)

    monkeypatch.setattr(sector_rotation_service, "get_sector_rotation", fake_rotation)
    monkeypatch.setattr(company_profile_service, "get_company_profile", fake_profile)
    monkeypatch.setattr(tavily_service, "fetch_news_summary", fake_news)
    monkeypatch.setattr(sec_edgar_service, "get_recent_filings", fake_filings)
    # Touch research_service to ensure it's loaded with any monkeypatched deps.
    assert research_service is not None


def _stub_polygon_financials(symbol: str) -> dict[str, Any]:
    return {
        "results": [
            {
                "fiscal_year": "2026",
                "fiscal_period": "Q1",
                "filing_date": "2026-04-30",
                "financials": {
                    "income_statement": {
                        "revenues": {"value": 100_000_000.0, "unit": "USD"},
                        "basic_earnings_per_share": {"value": 1.45, "unit": "USD"},
                        "diluted_earnings_per_share": {"value": 1.40, "unit": "USD"},
                        "operating_income_loss": {"value": 30_000_000.0, "unit": "USD"},
                    }
                },
            },
            {
                "fiscal_year": "2025",
                "fiscal_period": "Q4",
                "filing_date": "2026-01-30",
                "financials": {
                    "income_statement": {
                        "revenues": {"value": 90_000_000.0, "unit": "USD"},
                        "basic_earnings_per_share": {"value": 1.20, "unit": "USD"},
                    }
                },
            },
        ]
    }


def _patch_earnings_upstreams(
    monkeypatch, *, filing_text: str = "Filing body excerpt."
) -> None:
    from app.services import (
        company_profile_service,
        polygon_service,
        research_service,
        sec_edgar_service,
        tavily_service,
    )

    async def fake_profile(symbol: str, *, lang: str = "en") -> dict[str, Any]:
        return _stub_company_profile(symbol)

    async def fake_news(symbol: str, *, lang: str = "en") -> dict[str, Any]:
        return _stub_market_news(symbol)

    async def fake_filings(
        symbol: str,
        form_types: tuple[str, ...] = ("10-K", "10-Q", "8-K"),
        limit: int = 20,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        return _stub_recent_filings(symbol, limit=limit)

    async def fake_text(
        accession_number: str, *, max_chars: int = 200_000, force: bool = False
    ) -> dict[str, Any]:
        # Honour the caller's max_chars by trimming server-side.
        return _stub_filing_text(text=filing_text[:max_chars])

    async def fake_financials(
        ticker: str,
        *,
        limit: int = 4,
        period_of_report_type: str = "Q",
        force: bool = False,
    ) -> dict[str, Any]:
        return _stub_polygon_financials(ticker)

    monkeypatch.setattr(company_profile_service, "get_company_profile", fake_profile)
    monkeypatch.setattr(tavily_service, "fetch_news_summary", fake_news)
    monkeypatch.setattr(sec_edgar_service, "get_recent_filings", fake_filings)
    monkeypatch.setattr(sec_edgar_service, "get_filing_text", fake_text)
    monkeypatch.setattr(polygon_service, "get_financials", fake_financials)
    assert research_service is not None


# ---------------------------------------------------------------------------
# Stub LLM router used in run_* tests
# ---------------------------------------------------------------------------


class _StubRouter:
    """Captures the (system, user) pair and returns a canned text payload."""

    def __init__(self, payload_text: str, *, model: str = "stub-model") -> None:
        self.payload_text = payload_text
        self.model = model
        self.last_system: str = ""
        self.last_user: str = ""

    async def generate(self, *, system: str, user: str, model=None):
        from core.agents.llm_router import LLMResponse

        self.last_system = system
        self.last_user = user
        return LLMResponse(
            text=self.payload_text,
            model=self.model,
            tokens_in=42,
            tokens_out=17,
        )


class _UnavailableRouter:
    async def generate(self, *, system: str, user: str, model=None):
        from core.agents.llm_router import LLMRouterUnavailableError

        raise LLMRouterUnavailableError("stub: provider not configured")


def _market_research_json() -> str:
    return json.dumps(
        {
            "sector": "semiconductors",
            "theme": "AI accelerators",
            "industry_overview": (
                "The semiconductor sector is in a multi-year capex up-cycle "
                "led by AI training. Supply is constrained by leading-edge "
                "node availability."
            ),
            "key_drivers": [
                "Hyperscaler AI capex",
                "Edge inference rollout",
                "Foundry capacity at TSMC N3/N2",
            ],
            "competitive_landscape": (
                "Three-way oligopoly at the leading edge: TSMC for foundry, "
                "NVIDIA for accelerators, ASML for lithography."
            ),
            "peer_comps": {
                "peers": [
                    {
                        "symbol": "NVDA",
                        "name": "NVIDIA",
                        "market_cap": 3_000_000_000_000,
                        "pe_ratio": 45.0,
                        "ev_ebitda": 38.0,
                        "ps_ratio": 25.0,
                        "revenue_growth_yoy": 1.20,
                        "notes": "Leader.",
                    }
                ],
                "median_pe": 45.0,
                "median_ev_ebitda": 38.0,
                "commentary": "Premium multiples reflect AI exposure.",
            },
            "ideas_shortlist": [
                {
                    "symbol": "NVDA",
                    "thesis": "Best-positioned for AI training capex.",
                    "catalyst": "Q4 print",
                    "risk": "Customer concentration",
                }
            ],
            "key_risks": ["Capex digestion", "Export controls", "Cyclical inventory"],
            "sector_thesis": "Constructive over 12 months.",
        }
    )


def _earnings_review_json() -> str:
    return json.dumps(
        {
            "symbol": "NVDA",
            "period": "FY2025 Q3",
            "variance_table": [
                {
                    "metric": "Revenue",
                    "actual": 35_080_000_000,
                    "consensus": 33_200_000_000,
                    "prior": 18_120_000_000,
                    "surprise_pct": 0.057,
                    "commentary": "Driven by data-center.",
                }
            ],
            "guidance_changes": [
                {
                    "metric": "Q4 revenue",
                    "prior_guidance": None,
                    "new_guidance": "$37.5B +/- 2%",
                    "direction": "introduced",
                }
            ],
            "filing_highlights": [
                {
                    "accession_number": "0000000001-25-000001",
                    "form_type": "8-K",
                    "excerpt": "Blackwell ramp on schedule.",
                    "relevance": "Confirms supply timeline.",
                }
            ],
            "note_draft": (
                "NVDA delivered another beat-and-raise. Revenue exceeded "
                "the Street by ~6%, EPS by ~8%. Guidance ahead. We raise "
                "estimates and stay constructive."
            ),
            "key_takeaways": ["Beat-and-raise sustained", "Blackwell on track"],
            "follow_ups": ["Mix shift detail?", "Sovereign AI pipeline?"],
        }
    )


# ---------------------------------------------------------------------------
# build_market_research_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_market_research_context_happy_path(monkeypatch) -> None:
    from app.services import research_service

    _patch_market_research_upstreams(monkeypatch)

    ctx = await research_service.build_market_research_context(
        sector="Semiconductors", theme="AI accelerators", peer_count=4
    )

    assert ctx.sector == "Semiconductors"
    assert ctx.theme == "AI accelerators"
    assert len(ctx.peer_universe) == 4
    assert ctx.sector_returns.get("12m") == pytest.approx(0.45)
    assert len(ctx.peer_fundamentals) == 4
    assert all("symbol" in p and "market_cap" in p for p in ctx.peer_fundamentals)
    # News + filings clip per-symbol to a small N — just assert non-empty.
    assert len(ctx.news_summary) > 0
    assert len(ctx.recent_filings) > 0
    assert ctx.generated_at.tzinfo is not None


@pytest.mark.asyncio
async def test_build_market_research_context_degrades_when_sec_edgar_disabled(
    monkeypatch,
) -> None:
    from app.services import research_service, sec_edgar_service

    _patch_market_research_upstreams(monkeypatch)

    async def boom(*args, **kwargs):
        raise RuntimeError("SEC EDGAR integration is disabled")

    monkeypatch.setattr(sec_edgar_service, "get_recent_filings", boom)

    ctx = await research_service.build_market_research_context(
        sector="Semiconductors", peer_count=3
    )
    assert ctx.recent_filings == ()  # gracefully empty
    # Other channels still populated:
    assert len(ctx.peer_fundamentals) == 3
    assert len(ctx.peer_universe) == 3


@pytest.mark.asyncio
async def test_build_market_research_context_rejects_empty_sector() -> None:
    from app.services import research_service

    with pytest.raises(ValueError):
        await research_service.build_market_research_context(sector="")
    with pytest.raises(ValueError):
        await research_service.build_market_research_context(sector="   ")


# ---------------------------------------------------------------------------
# build_earnings_review_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_earnings_review_context_happy_path(monkeypatch) -> None:
    from app.services import research_service

    _patch_earnings_upstreams(monkeypatch)

    ctx = await research_service.build_earnings_review_context("nvda")

    assert ctx.symbol == "NVDA"
    assert ctx.fundamentals_now is not None
    assert ctx.fundamentals_now["sector"] == "Semiconductors"
    assert ctx.latest_filing is not None
    assert ctx.latest_filing["form_type"] in ("10-Q", "8-K")
    assert "excerpt" in ctx.latest_filing
    assert len(ctx.recent_filings) >= 1
    assert ctx.period is not None and "as of" in ctx.period
    assert ctx.consensus_estimates is None  # paid-feed territory
    # prior_actuals now populated from the polygon stub (2 quarters).
    assert len(ctx.prior_actuals) == 2
    most_recent = ctx.prior_actuals[0]
    assert most_recent["period"] == "2026 Q1"
    assert most_recent["revenue"] == 100_000_000.0
    assert most_recent["eps_basic"] == 1.45
    assert most_recent["eps_diluted"] == 1.40
    assert most_recent["operating_income"] == 30_000_000.0
    # The 2nd entry has missing eps_diluted/operating_income → must be None.
    older = ctx.prior_actuals[1]
    assert older["eps_diluted"] is None
    assert older["operating_income"] is None
    assert ctx.generated_at.tzinfo is not None


@pytest.mark.asyncio
async def test_build_earnings_review_context_rejects_empty_symbol() -> None:
    from app.services import research_service

    with pytest.raises(ValueError):
        await research_service.build_earnings_review_context("")


# ---------------------------------------------------------------------------
# run_market_research / run_earnings_review — happy path + persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_market_research_persists_when_persist_true(monkeypatch) -> None:
    from sqlalchemy import select

    from app.db.tables import ResearchOutput
    from app.services import research_service

    _patch_market_research_upstreams(monkeypatch)

    router = _StubRouter(_market_research_json())
    async with AsyncSessionLocal() as session:
        report = await research_service.run_market_research(
            sector="Semiconductors",
            theme="AI accelerators",
            peer_count=3,
            persist=True,
            db_session=session,
            router=router,
        )

    assert report.sector == "semiconductors"
    assert report.theme == "AI accelerators"
    assert len(report.peer_comps.peers) == 1
    # Verify exactly one ResearchOutput row, with the right kind/subject.
    async with AsyncSessionLocal() as session:
        rows = (
            (await session.execute(select(ResearchOutput))).scalars().all()
        )
    assert len(rows) == 1
    assert rows[0].kind == "market_research"
    assert rows[0].subject == "Semiconductors"
    assert rows[0].theme == "AI accelerators"
    assert rows[0].model_id == "stub-model"
    assert rows[0].cost_tokens_in == 42
    assert rows[0].cost_tokens_out == 17
    decoded = json.loads(rows[0].payload_json)
    assert decoded["sector"] == "semiconductors"


@pytest.mark.asyncio
async def test_run_market_research_does_not_persist_when_persist_false(
    monkeypatch,
) -> None:
    from sqlalchemy import select

    from app.db.tables import ResearchOutput
    from app.services import research_service

    _patch_market_research_upstreams(monkeypatch)

    router = _StubRouter(_market_research_json())
    report = await research_service.run_market_research(
        sector="Semiconductors",
        peer_count=3,
        persist=False,
        router=router,
    )
    assert report.sector == "semiconductors"

    async with AsyncSessionLocal() as session:
        rows = (
            (await session.execute(select(ResearchOutput))).scalars().all()
        )
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_run_earnings_review_persists_when_persist_true(monkeypatch) -> None:
    from sqlalchemy import select

    from app.db.tables import ResearchOutput
    from app.services import research_service

    _patch_earnings_upstreams(monkeypatch)

    router = _StubRouter(_earnings_review_json())
    async with AsyncSessionLocal() as session:
        review = await research_service.run_earnings_review(
            "nvda",
            persist=True,
            db_session=session,
            router=router,
        )

    assert review.symbol == "NVDA"
    assert review.period == "FY2025 Q3"
    assert len(review.variance_table) == 1

    async with AsyncSessionLocal() as session:
        rows = (
            (await session.execute(select(ResearchOutput))).scalars().all()
        )
    assert len(rows) == 1
    assert rows[0].kind == "earnings_review"
    assert rows[0].subject == "NVDA"
    assert rows[0].theme is None


@pytest.mark.asyncio
async def test_run_earnings_review_does_not_persist_when_persist_false(
    monkeypatch,
) -> None:
    from sqlalchemy import select

    from app.db.tables import ResearchOutput
    from app.services import research_service

    _patch_earnings_upstreams(monkeypatch)

    router = _StubRouter(_earnings_review_json())
    review = await research_service.run_earnings_review(
        "nvda", persist=False, router=router
    )
    assert review.symbol == "NVDA"

    async with AsyncSessionLocal() as session:
        rows = (
            (await session.execute(select(ResearchOutput))).scalars().all()
        )
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# LLMRouterUnavailableError propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_market_research_propagates_router_unavailable(monkeypatch) -> None:
    from core.agents.llm_router import LLMRouterUnavailableError
    from app.services import research_service

    _patch_market_research_upstreams(monkeypatch)

    with pytest.raises(LLMRouterUnavailableError):
        await research_service.run_market_research(
            sector="Semiconductors",
            peer_count=2,
            persist=False,
            router=_UnavailableRouter(),
        )


@pytest.mark.asyncio
async def test_run_earnings_review_propagates_router_unavailable(monkeypatch) -> None:
    from core.agents.llm_router import LLMRouterUnavailableError
    from app.services import research_service

    _patch_earnings_upstreams(monkeypatch)

    with pytest.raises(LLMRouterUnavailableError):
        await research_service.run_earnings_review(
            "nvda",
            persist=False,
            router=_UnavailableRouter(),
        )


# ---------------------------------------------------------------------------
# Filing-text truncation: long filings must be capped before LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_earnings_review_truncates_long_filing_text(monkeypatch) -> None:
    from app.services import research_service

    # 50_000-char filing — must be trimmed before going to the LLM.
    long_text = "X" * 50_000
    _patch_earnings_upstreams(monkeypatch, filing_text=long_text)

    router = _StubRouter(_earnings_review_json())
    await research_service.run_earnings_review(
        "nvda", persist=False, router=router
    )

    cap = research_service._FILING_EXCERPT_CHAR_CAP
    # The user prompt sent to the router contains the JSON-encoded context.
    # The filing excerpt inside it must be trimmed to the cap.
    assert "X" * (cap + 1) not in router.last_user
    assert "X" * cap in router.last_user


# ---------------------------------------------------------------------------
# Smart peer universe — sector-filter falls back gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_peer_universe_filters_by_sector(monkeypatch) -> None:
    from app.services import company_profile_service, research_service

    # Stub: every fallback name is "Semiconductors" except AAPL/MSFT/GOOGL.
    _SECTOR_BY = {
        "AAPL": "Information Technology",
        "MSFT": "Information Technology",
        "GOOGL": "Communication Services",
        "AMZN": "Consumer Discretionary",
        "META": "Communication Services",
        "NVDA": "Semiconductors",
        "AVGO": "Semiconductors",
        "AMD": "Semiconductors",
        "TSLA": "Consumer Discretionary",
        "JPM": "Financials",
    }

    async def fake_profile(symbol: str, *, lang: str = "en") -> dict[str, Any]:
        return {"sector": _SECTOR_BY.get(symbol, "Other"), "industry": "x"}

    monkeypatch.setattr(company_profile_service, "get_company_profile", fake_profile)

    # Avoid touching factor_data_service in this test.
    async def empty_russell() -> list[str]:
        return []

    monkeypatch.setattr(
        research_service, "_safe_get_russell_universe", empty_russell
    )

    peers = await research_service._resolve_peer_universe("Semiconductors", 6)
    # 3 fallback semis match → smart path returns just those 3.
    assert set(peers) == {"NVDA", "AVGO", "AMD"}


@pytest.mark.asyncio
async def test_resolve_peer_universe_falls_back_when_no_match(monkeypatch) -> None:
    from app.services import company_profile_service, research_service

    async def no_profile(symbol: str, *, lang: str = "en") -> dict[str, Any]:
        return {"sector": "Utilities", "industry": "Power"}

    async def empty_russell() -> list[str]:
        return []

    monkeypatch.setattr(company_profile_service, "get_company_profile", no_profile)
    monkeypatch.setattr(
        research_service, "_safe_get_russell_universe", empty_russell
    )

    # No fallback sym matches "Semiconductors" → falls back to unfiltered _FALLBACK_PEERS.
    peers = await research_service._resolve_peer_universe("Semiconductors", 4)
    assert len(peers) == 4
    assert peers == list(research_service._FALLBACK_PEERS[:4])


# ---------------------------------------------------------------------------
# list_research_history — read-side query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_research_history_returns_most_recent_first(monkeypatch) -> None:
    from app.db.tables import ResearchOutput
    from app.services import research_service

    _patch_market_research_upstreams(monkeypatch)

    # Persist two market_research rows + one earnings_review row.
    router_a = _StubRouter(_market_research_json())
    await research_service.run_market_research(
        sector="Semiconductors", peer_count=2, persist=True, router=router_a
    )
    router_b = _StubRouter(_market_research_json())
    await research_service.run_market_research(
        sector="Healthcare", peer_count=2, persist=True, router=router_b
    )
    _patch_earnings_upstreams(monkeypatch)
    router_c = _StubRouter(_earnings_review_json())
    await research_service.run_earnings_review("AAPL", persist=True, router=router_c)

    items = await research_service.list_research_history(limit=10)
    assert len(items) == 3
    # Most-recent-first: AAPL earnings_review came last.
    assert items[0].kind == "earnings_review"
    assert items[0].subject == "AAPL"
    assert isinstance(items[0].payload, dict)
    assert items[0].payload.get("symbol") == "NVDA"  # from the stub JSON
    assert items[0].model_id == "stub-model"
    assert items[0].cost_tokens_in == 42


@pytest.mark.asyncio
async def test_list_research_history_filters_by_kind(monkeypatch) -> None:
    from app.services import research_service

    _patch_market_research_upstreams(monkeypatch)
    await research_service.run_market_research(
        sector="Semiconductors",
        peer_count=2,
        persist=True,
        router=_StubRouter(_market_research_json()),
    )
    _patch_earnings_upstreams(monkeypatch)
    await research_service.run_earnings_review(
        "AAPL", persist=True, router=_StubRouter(_earnings_review_json())
    )

    market_only = await research_service.list_research_history(kind="market_research")
    earnings_only = await research_service.list_research_history(kind="earnings_review")

    assert len(market_only) == 1
    assert market_only[0].kind == "market_research"
    assert len(earnings_only) == 1
    assert earnings_only[0].kind == "earnings_review"


@pytest.mark.asyncio
async def test_list_research_history_filters_by_subject(monkeypatch) -> None:
    from app.services import research_service

    _patch_earnings_upstreams(monkeypatch)
    await research_service.run_earnings_review(
        "AAPL", persist=True, router=_StubRouter(_earnings_review_json())
    )
    await research_service.run_earnings_review(
        "NVDA", persist=True, router=_StubRouter(_earnings_review_json())
    )

    apple = await research_service.list_research_history(subject="AAPL")
    assert len(apple) == 1
    assert apple[0].subject == "AAPL"


@pytest.mark.asyncio
async def test_list_research_history_rejects_invalid_kind() -> None:
    from app.services import research_service

    with pytest.raises(ValueError):
        await research_service.list_research_history(kind="foo")


@pytest.mark.asyncio
async def test_list_research_history_clamps_limit(monkeypatch) -> None:
    from app.services import research_service

    _patch_market_research_upstreams(monkeypatch)
    # Persist 3 rows; ask for limit=1.
    for sector in ("Semis", "Health", "Energy"):
        await research_service.run_market_research(
            sector=sector,
            peer_count=2,
            persist=True,
            router=_StubRouter(_market_research_json()),
        )

    items = await research_service.list_research_history(limit=1)
    assert len(items) == 1
