"""Analyzer — orchestrates persona system prompt + context + LLM call → response."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from core.agents.base import KeyFactor, Persona, PersonaResponse
from core.agents.context import AnalysisContext
from core.agents.llm_router import LLMRouter


VALID_VERDICTS = {"buy", "hold", "sell"}


class AnalyzerParseError(ValueError):
    """The LLM returned text that didn't fit our expected JSON schema."""


class Analyzer:
    """Single entry point: `analyzer.run(persona, ctx)` → PersonaResponse."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def run(
        self,
        *,
        persona: Persona,
        ctx: AnalysisContext,
        model: Optional[str] = None,
    ) -> PersonaResponse:
        user_block = self._compose_user_message(ctx)
        llm_response = await self._router.generate(
            system=persona.system_prompt,
            user=user_block,
            model=model,
        )
        return self._parse_response(persona=persona, ctx=ctx, raw_text=llm_response.text)

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _compose_user_message(ctx: AnalysisContext) -> str:
        question_section = (
            f"\n\nUser question:\n{ctx.question.strip()}"
            if ctx.question and ctx.question.strip()
            else ""
        )
        return f"Context for symbol {ctx.symbol}:\n\n{ctx.to_json_block()}{question_section}"

    @staticmethod
    def _parse_response(
        *,
        persona: Persona,
        ctx: AnalysisContext,
        raw_text: str,
    ) -> PersonaResponse:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise AnalyzerParseError(
                f"Response is not valid JSON: {exc}\nRaw text: {raw_text[:300]}"
            ) from exc

        verdict = str(payload.get("verdict", "")).lower().strip()
        if verdict not in VALID_VERDICTS:
            raise AnalyzerParseError(
                f"Invalid verdict {verdict!r}, expected one of {sorted(VALID_VERDICTS)}"
            )

        confidence_raw = payload.get("confidence", 0.5)
        try:
            confidence = max(0.0, min(1.0, float(confidence_raw)))
        except (TypeError, ValueError):
            confidence = 0.5

        reasoning_summary = str(payload.get("reasoning_summary", "")).strip()
        if not reasoning_summary:
            raise AnalyzerParseError("reasoning_summary is empty or missing")

        key_factors_raw = payload.get("key_factors", []) or []
        key_factors: list[KeyFactor] = []
        for entry in key_factors_raw:
            if not isinstance(entry, dict):
                continue
            try:
                weight = max(0.0, min(1.0, float(entry.get("weight", 0.0))))
            except (TypeError, ValueError):
                weight = 0.0
            key_factors.append(KeyFactor(
                signal=str(entry.get("signal", "")).strip() or "other",
                weight=weight,
                interpretation=str(entry.get("interpretation", "")).strip(),
            ))

        follow_up_raw = payload.get("follow_up_questions", []) or []
        follow_up = [
            str(q).strip()
            for q in follow_up_raw
            if isinstance(q, (str, int, float)) and str(q).strip()
        ]

        return PersonaResponse(
            persona_id=persona.id,
            symbol=ctx.symbol,
            verdict=verdict,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            key_factors=key_factors,
            follow_up_questions=follow_up,
            raw_question=ctx.question,
            generated_at=datetime.now(timezone.utc),
        )
