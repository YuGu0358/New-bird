"""Research service — context builders + run_* entry points for research personas.

Mirrors the `LiveContextBuilder` pattern in `agents_service.py`: each external
data source is wrapped in a try/except so a single flaky upstream never
blocks the whole pipeline. Missing pieces become None / empty tuples in the
context dataclass and the LLM is told there is no data for that channel.

Public surface:
    build_market_research_context(sector, theme=None, peer_count=10)
    build_earnings_review_context(symbol)
    run_market_research(sector, theme=None, peer_count=10, *, persist=True, ...)
    run_earnings_review(symbol, *, persist=True, ...)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import AsyncSessionLocal
from app.db.tables import ResearchOutput
from app.services import (
    company_profile_service,
    sec_edgar_service,
    sector_rotation_service,
    tavily_service,
)
from core.agents.llm_router import LLMRouter, get_default_router
from core.agents.research_analyzer import ResearchAnalyzer
from core.agents.research_personas import (
    EARNINGS_REVIEWER_PERSONA,
    MARKET_RESEARCHER_PERSONA,
)
from core.agents.research_schemas import EarningsReview, MarketResearchReport

logger = logging.getLogger(__name__)


# Cap each filing-text excerpt that flows into the LLM context. SEC filings
# can balloon to hundreds of KB and chew through the model's context budget.
# 5_000 chars is enough for a press-release lede + key tables but bounded.
_FILING_EXCERPT_CHAR_CAP = 5_000

# Cap on the number of peers we include in market research context. The LLM
# does its own shortlist; sending more than ~12 peers is noise.
_MAX_PEERS_HARD_CAP = 12

# Default fallback peer universe when we cannot derive one from the live
# services. Picked to be sector-diverse so the LLM at least has *something*
# to start from when factor/sector services are unavailable.
_FALLBACK_PEERS: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "AVGO",
    "AMD",
    "TSLA",
    "JPM",
)


# ---------------------------------------------------------------------------
# Immutable context dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketResearchContext:
    sector: str
    theme: Optional[str]
    peer_universe: tuple[str, ...]
    sector_returns: dict[str, float]
    peer_fundamentals: tuple[dict[str, Any], ...]
    news_summary: tuple[dict[str, Any], ...]
    recent_filings: tuple[dict[str, Any], ...]
    generated_at: datetime


@dataclass(frozen=True)
class EarningsReviewContext:
    symbol: str
    period: Optional[str]
    latest_filing: Optional[dict[str, Any]]
    prior_actuals: tuple[dict[str, Any], ...]
    consensus_estimates: Optional[dict[str, Any]]
    fundamentals_now: Optional[dict[str, Any]]
    fundamentals_prior: Optional[dict[str, Any]]
    recent_news: tuple[dict[str, Any], ...]
    recent_filings: tuple[dict[str, Any], ...]
    generated_at: datetime


# ---------------------------------------------------------------------------
# Market-research context builder
# ---------------------------------------------------------------------------


async def build_market_research_context(
    sector: str,
    theme: Optional[str] = None,
    peer_count: int = 10,
) -> MarketResearchContext:
    """Assemble the JSON-friendly context the market-researcher persona consumes.

    Each upstream pull is independently fallible — a failure in one channel
    must not block the others. SEC EDGAR in particular often raises
    ``RuntimeError`` (no UA configured); that degrades to an empty filings
    tuple rather than a top-level failure.
    """
    if not sector or not sector.strip():
        raise ValueError("sector must be a non-empty string")
    sector_clean = sector.strip()
    cap = max(1, min(int(peer_count or 1), _MAX_PEERS_HARD_CAP))

    peer_universe = await _resolve_peer_universe(sector_clean, cap)
    sector_returns = await _fetch_sector_returns(sector_clean)
    peer_fundamentals = await _fetch_peer_fundamentals(peer_universe)
    news_summary = await _fetch_universe_news(peer_universe)
    recent_filings = await _fetch_universe_filings(peer_universe)

    return MarketResearchContext(
        sector=sector_clean,
        theme=theme.strip() if isinstance(theme, str) and theme.strip() else None,
        peer_universe=tuple(peer_universe),
        sector_returns=dict(sector_returns),
        peer_fundamentals=tuple(peer_fundamentals),
        news_summary=tuple(news_summary),
        recent_filings=tuple(recent_filings),
        generated_at=datetime.now(timezone.utc),
    )


async def _resolve_peer_universe(sector: str, peer_count: int) -> list[str]:
    """Pick a peer ticker list for the sector.

    We don't have a `factor_fundamentals_service` peer-rank endpoint here.
    Strategy: use the static ``_FALLBACK_PEERS`` list as a safe baseline and
    let the LLM pick the actually-relevant ones inside the report. The
    deterministic comps endpoint (Phase 4) builds a tighter list from
    ``multi_factor_score_service`` peer rank + ``company_profile_service``.
    """
    return list(_FALLBACK_PEERS[:peer_count])


async def _fetch_sector_returns(sector: str) -> dict[str, float]:
    """Pull sector-rotation returns for the named sector. Empty on failure."""
    try:
        rotation = await sector_rotation_service.get_sector_rotation()
    except Exception as exc:  # noqa: BLE001
        logger.debug("sector_rotation failed for %s: %s", sector, exc)
        return {}
    if not rotation:
        return {}
    rows = rotation.get("rows") or []
    sector_lower = sector.lower()
    target = next(
        (
            r
            for r in rows
            if isinstance(r, dict)
            and str(r.get("sector") or "").strip().lower() == sector_lower
        ),
        None,
    )
    if target is None:
        return {}
    raw_returns = target.get("returns") or {}
    if not isinstance(raw_returns, dict):
        return {}
    out: dict[str, float] = {}
    for window, value in raw_returns.items():
        try:
            out[str(window)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


async def _fetch_peer_fundamentals(symbols: list[str]) -> list[dict[str, Any]]:
    """Per-peer fundamentals snapshot via company_profile_service."""
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            profile = await company_profile_service.get_company_profile(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug("company profile failed for %s: %s", symbol, exc)
            continue
        if not profile:
            continue
        out.append(
            {
                "symbol": symbol,
                "company_name": profile.get("company_name"),
                "sector": profile.get("sector"),
                "industry": profile.get("industry"),
                "market_cap": profile.get("market_cap"),
                "currency": profile.get("currency"),
            }
        )
    return out


async def _fetch_universe_news(symbols: list[str]) -> list[dict[str, Any]]:
    """Pull recent headlines per symbol. Capped to keep prompts bounded."""
    out: list[dict[str, Any]] = []
    for symbol in symbols[:5]:  # 5 names is plenty for sector context
        try:
            payload = await tavily_service.fetch_news_summary(symbol)
        except Exception as exc:  # noqa: BLE001
            logger.debug("news failed for %s: %s", symbol, exc)
            continue
        if payload is None:
            continue
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        items = payload.get("items") if isinstance(payload, dict) else None
        if not items and isinstance(payload, dict) and payload.get("summary"):
            items = [
                {
                    "title": payload.get("title") or symbol,
                    "summary": payload.get("summary"),
                    "source": payload.get("source") or "Tavily",
                    "at": payload.get("timestamp"),
                }
            ]
        for item in (items or [])[:3]:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "symbol": symbol,
                    "title": str(item.get("title") or "")[:200],
                    "summary": str(item.get("summary") or item.get("content") or "")[:500],
                    "source": str(item.get("source") or ""),
                    "at": item.get("at") or item.get("timestamp"),
                }
            )
    return out


async def _fetch_universe_filings(symbols: list[str]) -> list[dict[str, Any]]:
    """Pull SEC filings for each peer. Degrades to empty on RuntimeError."""
    out: list[dict[str, Any]] = []
    for symbol in symbols[:5]:
        try:
            payload = await sec_edgar_service.get_recent_filings(symbol, limit=3)
        except RuntimeError as exc:
            # Disabled gate or missing UA — skip the whole filings channel.
            logger.info("sec_edgar disabled for sector context: %s", exc)
            return []
        except LookupError as exc:
            logger.debug("sec_edgar no CIK for %s: %s", symbol, exc)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.debug("sec_edgar failed for %s: %s", symbol, exc)
            continue
        for filing in (payload.get("filings") or [])[:3]:
            if not isinstance(filing, dict):
                continue
            out.append({"symbol": symbol, **filing})
    return out


# ---------------------------------------------------------------------------
# Earnings-review context builder
# ---------------------------------------------------------------------------


async def build_earnings_review_context(symbol: str) -> EarningsReviewContext:
    """Assemble per-symbol context for the earnings-reviewer persona."""
    if not symbol or not symbol.strip():
        raise ValueError("symbol must be a non-empty ticker")
    sym = symbol.strip().upper()

    fundamentals_now = await _fetch_single_profile(sym)
    recent_news = await _fetch_symbol_news(sym)
    recent_filings = await _fetch_symbol_filings(sym)
    latest_filing = await _fetch_latest_filing_excerpt(recent_filings)
    period = _infer_period(latest_filing, recent_filings)

    return EarningsReviewContext(
        symbol=sym,
        period=period,
        latest_filing=latest_filing,
        prior_actuals=(),  # No earnings-actuals source wired in this phase.
        consensus_estimates=None,  # Same — paid-feed territory.
        fundamentals_now=fundamentals_now,
        fundamentals_prior=None,  # Out of scope without a snapshot table.
        recent_news=tuple(recent_news),
        recent_filings=tuple(recent_filings),
        generated_at=datetime.now(timezone.utc),
    )


async def _fetch_single_profile(symbol: str) -> Optional[dict[str, Any]]:
    try:
        profile = await company_profile_service.get_company_profile(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.debug("company profile failed for %s: %s", symbol, exc)
        return None
    if not profile:
        return None
    return {
        "symbol": symbol,
        "company_name": profile.get("company_name"),
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "market_cap": profile.get("market_cap"),
        "currency": profile.get("currency"),
    }


async def _fetch_symbol_news(symbol: str) -> list[dict[str, Any]]:
    try:
        payload = await market_research_service.get_news(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.debug("news failed for %s: %s", symbol, exc)
        return []
    if payload is None:
        return []
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    items = payload.get("items") if isinstance(payload, dict) else None
    out: list[dict[str, Any]] = []
    for item in (items or [])[:5]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": str(item.get("title") or "")[:200],
                "summary": str(item.get("summary") or item.get("content") or "")[:500],
                "source": str(item.get("source") or ""),
                "at": item.get("at") or item.get("timestamp"),
            }
        )
    return out


async def _fetch_symbol_filings(symbol: str) -> list[dict[str, Any]]:
    try:
        payload = await sec_edgar_service.get_recent_filings(
            symbol, form_types=("10-Q", "8-K", "10-K"), limit=10
        )
    except RuntimeError as exc:
        logger.info("sec_edgar disabled for earnings context: %s", exc)
        return []
    except LookupError as exc:
        logger.debug("sec_edgar no CIK for %s: %s", symbol, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.debug("sec_edgar filings failed for %s: %s", symbol, exc)
        return []
    return [f for f in (payload.get("filings") or []) if isinstance(f, dict)]


async def _fetch_latest_filing_excerpt(
    filings: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Pull the text snapshot of the most recent 10-Q or 8-K. Truncated."""
    if not filings:
        return None
    target = next(
        (
            f
            for f in filings
            if str(f.get("form_type") or "").upper() in ("10-Q", "8-K")
        ),
        None,
    )
    if target is None:
        target = filings[0]
    accession = str(target.get("accession_number") or "")
    if not accession:
        return None
    try:
        payload = await sec_edgar_service.get_filing_text(
            accession, max_chars=_FILING_EXCERPT_CHAR_CAP
        )
    except RuntimeError as exc:
        logger.info("sec_edgar filing text disabled: %s", exc)
        return None
    except LookupError as exc:
        logger.debug("sec_edgar filing text not found: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug("sec_edgar filing text failed: %s", exc)
        return None
    text_value = payload.get("text") or ""
    truncated_text = text_value[:_FILING_EXCERPT_CHAR_CAP]
    return {
        "accession_number": accession,
        "form_type": target.get("form_type"),
        "filing_date": target.get("filing_date"),
        "primary_doc_url": target.get("primary_doc_url"),
        "excerpt": truncated_text,
        "truncated": len(text_value) > _FILING_EXCERPT_CHAR_CAP,
    }


def _infer_period(
    latest_filing: Optional[dict[str, Any]],
    recent_filings: list[dict[str, Any]],
) -> Optional[str]:
    """Best-effort period string from filing metadata."""
    if latest_filing:
        date_str = latest_filing.get("filing_date") or ""
        if date_str:
            return f"as of {date_str}"
    for f in recent_filings:
        date_str = f.get("filing_date") or ""
        if date_str:
            return f"as of {date_str}"
    return None


# ---------------------------------------------------------------------------
# run_* entry points — context → LLM → parse → persist
# ---------------------------------------------------------------------------


async def run_market_research(
    sector: str,
    theme: Optional[str] = None,
    peer_count: int = 10,
    *,
    persist: bool = True,
    db_session: Optional[AsyncSession] = None,
    router: Optional[LLMRouter] = None,
) -> MarketResearchReport:
    """Build context, call the LLM, parse, optionally persist, return report."""
    ctx = await build_market_research_context(
        sector=sector, theme=theme, peer_count=peer_count
    )
    payload = _context_to_json_dict(ctx)
    chosen_router = router or get_default_router()
    response = await chosen_router.generate(
        system=MARKET_RESEARCHER_PERSONA.system_prompt,
        user=json.dumps(payload, default=_json_default),
    )
    report = ResearchAnalyzer().parse_market_research(response.text)

    if persist:
        await _persist_report(
            kind="market_research",
            subject=ctx.sector,
            theme=ctx.theme,
            report=report,
            response_model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            session=db_session,
        )
    return report


async def run_earnings_review(
    symbol: str,
    *,
    persist: bool = True,
    db_session: Optional[AsyncSession] = None,
    router: Optional[LLMRouter] = None,
) -> EarningsReview:
    """Build context, call the LLM, parse, optionally persist, return review."""
    ctx = await build_earnings_review_context(symbol=symbol)
    payload = _context_to_json_dict(ctx)
    chosen_router = router or get_default_router()
    response = await chosen_router.generate(
        system=EARNINGS_REVIEWER_PERSONA.system_prompt,
        user=json.dumps(payload, default=_json_default),
    )
    review = ResearchAnalyzer().parse_earnings_review(response.text)

    if persist:
        await _persist_report(
            kind="earnings_review",
            subject=ctx.symbol,
            theme=None,
            report=review,
            response_model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            session=db_session,
        )
    return review


# ---------------------------------------------------------------------------
# Serialisation + persistence helpers
# ---------------------------------------------------------------------------


def _context_to_json_dict(ctx: Any) -> dict[str, Any]:
    """Convert an immutable context dataclass to a plain JSON-able dict."""
    if not is_dataclass(ctx):
        raise TypeError(f"expected dataclass, got {type(ctx).__name__}")
    return asdict(ctx)


def _json_default(value: Any) -> Any:
    """`json.dumps` fallback for datetime + tuple-like leftovers."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return str(value)


async def _persist_report(
    *,
    kind: str,
    subject: str,
    theme: Optional[str],
    report: Any,
    response_model: Optional[str],
    tokens_in: Optional[int],
    tokens_out: Optional[int],
    session: Optional[AsyncSession],
) -> None:
    """Insert one ResearchOutput row. Uses caller's session, or a fresh one."""
    payload_json = json.dumps(_serialise_report(report), default=_json_default)
    row = ResearchOutput(
        kind=kind,
        subject=subject,
        theme=theme,
        payload_json=payload_json,
        model_id=response_model,
        cost_tokens_in=tokens_in,
        cost_tokens_out=tokens_out,
    )
    if session is not None:
        session.add(row)
        await session.commit()
        return
    async with AsyncSessionLocal() as owned_session:
        owned_session.add(row)
        await owned_session.commit()


def _serialise_report(report: Any) -> dict[str, Any]:
    """Convert a parsed research dataclass to a JSON-friendly dict."""
    if is_dataclass(report):
        return asdict(report)
    if isinstance(report, dict):
        return report
    raise TypeError(f"unsupported report type: {type(report).__name__}")
