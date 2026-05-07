"""Defensive JSON parser for research persona outputs.

The market-researcher and earnings-reviewer personas return rich
structured payloads (peer comp tables, variance tables, note drafts)
that don't fit the buy/hold/sell shape parsed by `analyzer.Analyzer`.

`ResearchAnalyzer` provides two pure-function methods that take an LLM
response string and return immutable dataclass instances. It tolerates
common LLM tics:
- markdown code fences (```json ... ```)
- leading/trailing whitespace
- extra unexpected fields (forward compatibility)

It raises `ResearchAnalyzerParseError` on schema mismatch (missing
required fields, wrong types).
"""
from __future__ import annotations

import json
from typing import Any, Optional

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


VALID_GUIDANCE_DIRECTIONS = {"raised", "lowered", "maintained", "introduced"}


class ResearchAnalyzerParseError(ValueError):
    """The LLM response did not match the expected research schema."""


class ResearchAnalyzer:
    """Pure parser. Stateless — one instance per call site is fine."""

    def parse_market_research(self, raw: str) -> MarketResearchReport:
        payload = _decode_json(raw)
        try:
            return _build_market_research_report(payload)
        except ResearchAnalyzerParseError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ResearchAnalyzerParseError(
                f"Failed to map JSON to MarketResearchReport: {exc}"
            ) from exc

    def parse_earnings_review(self, raw: str) -> EarningsReview:
        payload = _decode_json(raw)
        try:
            return _build_earnings_review(payload)
        except ResearchAnalyzerParseError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ResearchAnalyzerParseError(
                f"Failed to map JSON to EarningsReview: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Decoding — markdown fence stripping + json.loads
# ---------------------------------------------------------------------------


def _decode_json(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ResearchAnalyzerParseError(
            f"Expected raw response to be str, got {type(raw).__name__}"
        )
    cleaned = _strip_markdown_fences(raw).strip()
    if not cleaned:
        raise ResearchAnalyzerParseError("Empty response after fence stripping")
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ResearchAnalyzerParseError(
            f"Response is not valid JSON: {exc}\nRaw text: {cleaned[:300]}"
        ) from exc
    if not isinstance(payload, dict):
        raise ResearchAnalyzerParseError(
            f"Top-level JSON must be an object, got {type(payload).__name__}"
        )
    return payload


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` (or plain ``` ... ```) wrappers if present.

    Defensive against LLMs that ignore "no markdown fences" instructions.
    Returns the original text untouched if no fences are detected.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    # Drop the opening fence line (``` or ```json or ```JSON etc.)
    first_newline = stripped.find("\n")
    if first_newline == -1:
        # Single-line fence — nothing useful between fences; strip them all.
        return stripped.strip("`")
    body = stripped[first_newline + 1 :]
    # Drop the closing fence.
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -len("```")]
    return body


# ---------------------------------------------------------------------------
# Required-field helpers
# ---------------------------------------------------------------------------


def _require_str(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ResearchAnalyzerParseError(f"Missing required field: {key!r}")
    value = payload[key]
    if not isinstance(value, str):
        raise ResearchAnalyzerParseError(
            f"Field {key!r} must be a string, got {type(value).__name__}"
        )
    return value


def _opt_str(payload: dict[str, Any], key: str) -> Optional[str]:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str):
        # Coerce simple scalars; fail on structured types so we don't silently
        # flatten an object into "{...}".
        if isinstance(value, (int, float, bool)):
            return str(value)
        raise ResearchAnalyzerParseError(
            f"Field {key!r} must be a string or null, got {type(value).__name__}"
        )
    return value


def _opt_float(payload: dict[str, Any], key: str) -> Optional[float]:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ResearchAnalyzerParseError(
            f"Field {key!r} must be a number or null, got {value!r}"
        ) from exc


def _require_str_tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    if key not in payload:
        raise ResearchAnalyzerParseError(f"Missing required field: {key!r}")
    value = payload[key]
    if not isinstance(value, list):
        raise ResearchAnalyzerParseError(
            f"Field {key!r} must be an array, got {type(value).__name__}"
        )
    return tuple(str(item) for item in value if item is not None)


def _require_list(payload: dict[str, Any], key: str) -> list[Any]:
    if key not in payload:
        raise ResearchAnalyzerParseError(f"Missing required field: {key!r}")
    value = payload[key]
    if not isinstance(value, list):
        raise ResearchAnalyzerParseError(
            f"Field {key!r} must be an array, got {type(value).__name__}"
        )
    return value


def _require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in payload:
        raise ResearchAnalyzerParseError(f"Missing required field: {key!r}")
    value = payload[key]
    if not isinstance(value, dict):
        raise ResearchAnalyzerParseError(
            f"Field {key!r} must be an object, got {type(value).__name__}"
        )
    return value


# ---------------------------------------------------------------------------
# MarketResearchReport builders
# ---------------------------------------------------------------------------


def _build_market_research_report(payload: dict[str, Any]) -> MarketResearchReport:
    sector = _require_str(payload, "sector")
    theme = _opt_str(payload, "theme")
    industry_overview = _require_str(payload, "industry_overview")
    key_drivers = _require_str_tuple(payload, "key_drivers")
    competitive_landscape = _require_str(payload, "competitive_landscape")
    peer_comps = _build_peer_comps(_require_dict(payload, "peer_comps"))
    ideas_shortlist = tuple(
        _build_idea_shortlist_item(item)
        for item in _require_list(payload, "ideas_shortlist")
        if isinstance(item, dict)
    )
    key_risks = _require_str_tuple(payload, "key_risks")
    sector_thesis = _require_str(payload, "sector_thesis")

    return MarketResearchReport(
        sector=sector,
        theme=theme,
        industry_overview=industry_overview,
        key_drivers=key_drivers,
        competitive_landscape=competitive_landscape,
        peer_comps=peer_comps,
        ideas_shortlist=ideas_shortlist,
        key_risks=key_risks,
        sector_thesis=sector_thesis,
    )


def _build_peer_comps(payload: dict[str, Any]) -> PeerComps:
    raw_peers = payload.get("peers", [])
    if not isinstance(raw_peers, list):
        raise ResearchAnalyzerParseError(
            f"peer_comps.peers must be an array, got {type(raw_peers).__name__}"
        )
    peers = tuple(
        _build_peer_row(item) for item in raw_peers if isinstance(item, dict)
    )
    median_pe = _opt_float(payload, "median_pe")
    median_ev_ebitda = _opt_float(payload, "median_ev_ebitda")
    commentary = _require_str(payload, "commentary")
    return PeerComps(
        peers=peers,
        median_pe=median_pe,
        median_ev_ebitda=median_ev_ebitda,
        commentary=commentary,
    )


def _build_peer_row(payload: dict[str, Any]) -> PeerRow:
    return PeerRow(
        symbol=_require_str(payload, "symbol"),
        name=_opt_str(payload, "name"),
        market_cap=_opt_float(payload, "market_cap"),
        pe_ratio=_opt_float(payload, "pe_ratio"),
        ev_ebitda=_opt_float(payload, "ev_ebitda"),
        ps_ratio=_opt_float(payload, "ps_ratio"),
        revenue_growth_yoy=_opt_float(payload, "revenue_growth_yoy"),
        notes=_opt_str(payload, "notes"),
    )


def _build_idea_shortlist_item(payload: dict[str, Any]) -> IdeaShortlistItem:
    return IdeaShortlistItem(
        symbol=_require_str(payload, "symbol"),
        thesis=_require_str(payload, "thesis"),
        catalyst=_opt_str(payload, "catalyst"),
        risk=_opt_str(payload, "risk"),
    )


# ---------------------------------------------------------------------------
# EarningsReview builders
# ---------------------------------------------------------------------------


def _build_earnings_review(payload: dict[str, Any]) -> EarningsReview:
    symbol = _require_str(payload, "symbol")
    period = _require_str(payload, "period")
    variance_table = tuple(
        _build_variance_row(item)
        for item in _require_list(payload, "variance_table")
        if isinstance(item, dict)
    )
    guidance_changes = tuple(
        _build_guidance_change(item)
        for item in _require_list(payload, "guidance_changes")
        if isinstance(item, dict)
    )
    filing_highlights = tuple(
        _build_filing_highlight(item)
        for item in _require_list(payload, "filing_highlights")
        if isinstance(item, dict)
    )
    note_draft = _require_str(payload, "note_draft")
    key_takeaways = _require_str_tuple(payload, "key_takeaways")
    follow_ups = _require_str_tuple(payload, "follow_ups")

    return EarningsReview(
        symbol=symbol,
        period=period,
        variance_table=variance_table,
        guidance_changes=guidance_changes,
        filing_highlights=filing_highlights,
        note_draft=note_draft,
        key_takeaways=key_takeaways,
        follow_ups=follow_ups,
    )


def _build_variance_row(payload: dict[str, Any]) -> VarianceRow:
    return VarianceRow(
        metric=_require_str(payload, "metric"),
        actual=_opt_float(payload, "actual"),
        consensus=_opt_float(payload, "consensus"),
        prior=_opt_float(payload, "prior"),
        surprise_pct=_opt_float(payload, "surprise_pct"),
        commentary=_opt_str(payload, "commentary"),
    )


def _build_guidance_change(payload: dict[str, Any]) -> GuidanceChange:
    metric = _require_str(payload, "metric")
    direction = _require_str(payload, "direction").strip().lower()
    if direction not in VALID_GUIDANCE_DIRECTIONS:
        raise ResearchAnalyzerParseError(
            f"guidance_changes[].direction must be one of "
            f"{sorted(VALID_GUIDANCE_DIRECTIONS)}, got {direction!r}"
        )
    return GuidanceChange(
        metric=metric,
        prior_guidance=_opt_str(payload, "prior_guidance"),
        new_guidance=_opt_str(payload, "new_guidance"),
        direction=direction,
    )


def _build_filing_highlight(payload: dict[str, Any]) -> FilingHighlight:
    return FilingHighlight(
        accession_number=_opt_str(payload, "accession_number"),
        form_type=_require_str(payload, "form_type"),
        excerpt=_require_str(payload, "excerpt"),
        relevance=_require_str(payload, "relevance"),
    )
