"""Core agent framework — pure dataclasses with no external deps.

Anything that knows how to talk to a broker, polygon, openai, or our DB
lives in `app/services/agents_service.py`. This module stays clean so
unit tests don't need network or DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class SignalWeights:
    """How much each information channel matters to a persona.

    All values are in [0.0, 1.0]. They DON'T need to sum to 1 — they're
    relative emphasis hints embedded into the system prompt so the LLM
    weighs evidence accordingly.
    """

    fundamentals: float = 0.5
    news: float = 0.5
    social: float = 0.5
    technical: float = 0.5
    macro: float = 0.5

    def as_dict(self) -> dict[str, float]:
        return {
            "fundamentals": self.fundamentals,
            "news": self.news,
            "social": self.social,
            "technical": self.technical,
            "macro": self.macro,
        }


@dataclass(frozen=True)
class Persona:
    """A named investment persona with style + signal weights + prompt."""

    id: str
    name: str
    style: str
    description: str
    system_prompt: str
    weights: SignalWeights = field(default_factory=SignalWeights)

    def public_view(self) -> dict[str, object]:
        """Frontend-safe representation (omits the full system prompt)."""
        return {
            "id": self.id,
            "name": self.name,
            "style": self.style,
            "description": self.description,
            "weights": self.weights.as_dict(),
        }


@dataclass(frozen=True)
class KeyFactor:
    """One piece of evidence the persona cited in its decision."""

    signal: str  # "fundamentals" | "news" | "social" | "technical" | "macro" | other
    weight: float  # 0.0 - 1.0, how heavily it influenced the verdict
    interpretation: str


@dataclass(frozen=True)
class ActionPlan:
    """Concrete buy/sell timing the user can actually act on.

    Every field is optional so a persona that genuinely doesn't have a
    view (e.g. a Graham analysis on a name well outside his framework)
    can return an empty plan rather than fabricated levels. The UI
    falls back to a "no plan" message when all primary fields are None.
    """

    should_buy_now: Optional[bool] = None
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    time_horizon: Optional[str] = None       # e.g. "intraday" / "1-3 months"
    trigger_condition: Optional[str] = None  # the WHEN — free-text rule


@dataclass(frozen=True)
class PersonaResponse:
    """Structured output of a single Analyzer.run() call."""

    persona_id: str
    symbol: str
    verdict: str  # "buy" | "hold" | "sell"
    confidence: float  # 0.0 - 1.0
    reasoning_summary: str
    key_factors: list[KeyFactor] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    action_plan: Optional[ActionPlan] = None
    raw_question: Optional[str] = None
    generated_at: Optional[datetime] = None
