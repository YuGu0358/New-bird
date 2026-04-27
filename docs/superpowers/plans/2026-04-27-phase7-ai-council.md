# Phase 7 — AI Council (Persona-driven Investment Analysis)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persona-based AI analyst system. 5 famous-investor personas (Buffett, Graham, Lynch, Soros, Burry) plus 1 home-grown **Sentinel** persona that fuses our P5 social-signal data + market data + news to deliver multi-source analysis. Every analysis returns a **structured** verdict (`buy`/`hold`/`sell` + confidence + reasoning factors), persists to DB, and is exposed via 4 REST endpoints. Frontend `IntelligencePage` becomes a real product page.

**Architecture (clean 3-layer split):**

```
┌─────────────────────────────────────────────────────────────────┐
│                   backend/core/agents/   (pure framework)       │
│                                                                 │
│   base.py              Persona dataclass, PersonaResponse       │
│   personas.py          6 built-in personas (system prompts)     │
│   context.py           AnalysisContext + ContextBuilder         │
│   llm_router.py        OpenAI-first call wrapper                │
│   analyzer.py          orchestrator: persona + ctx → response   │
│                                                                 │
│   Knows nothing about:                                          │
│   - FastAPI / SQLAlchemy / DB                                   │
│   - alpaca_service / polygon_service                            │
│   It receives everything via dependency injection.              │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│             backend/app/services/agents_service.py              │
│                                                                 │
│   - Wires the framework into our concrete data services         │
│     (alpaca / polygon / chart / company / news / social_signal) │
│   - Persists each analysis to AgentAnalysis table               │
│   - Returns API-ready dicts                                     │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│             backend/app/routers/agents.py  (4 endpoints)        │
│                                                                 │
│   GET  /api/agents/personas               list 6 personas       │
│   POST /api/agents/analyze                single-persona run    │
│   POST /api/agents/council                multi-persona fan-out │
│   GET  /api/agents/history?symbol=X       past analyses         │
└─────────────────────────────────────────────────────────────────┘
```

Each layer has one responsibility. The `core/agents/` module is independently unit-testable without spinning up the FastAPI app or hitting real markets.

**Tech Stack:** Python 3.13, OpenAI SDK (already a dep), Pydantic v2, FastAPI, SQLAlchemy async. **No new top-level dependencies.**

**Out of scope (deferred):**
- Multi-LLM provider router (Anthropic/Claude, DeepSeek, Ollama). P7 uses OpenAI only. Provider abstraction is structurally there (`llm_router.py`), but only one driver is wired.
- Streaming responses — P7 returns complete JSON.
- Frontend chat-style multi-turn conversation. P7 is one-shot analysis per submit. Multi-turn is P7.5 if needed.
- Persona editing UI (custom personas). The 6 built-in are hard-coded in P7.
- Council "synthesis" — P7 returns N parallel analyses; combining them into a meta-summary is P7.5.

---

## File Structure

### New packages
| Path | Responsibility |
|---|---|
| `backend/core/agents/__init__.py` | Public API re-exports |
| `backend/core/agents/base.py` | `Persona` dataclass + response dataclasses + ABC interfaces |
| `backend/core/agents/personas.py` | 6 built-in personas (Buffett / Graham / Lynch / Soros / Burry / Sentinel) with system prompts and signal weights |
| `backend/core/agents/context.py` | `AnalysisContext` (price + fundamentals + news + social + position) + `ContextBuilder` ABC |
| `backend/core/agents/llm_router.py` | `LLMRouter` ABC + `OpenAILLMRouter` implementation; structured JSON output |
| `backend/core/agents/analyzer.py` | `Analyzer` — composes persona system prompt + context + LLM call → `PersonaResponse` |

### New service + router
| Path | Responsibility |
|---|---|
| `backend/app/services/agents_service.py` | Concrete `ContextBuilder` impl that pulls from alpaca/polygon/chart/company/news/social services; persists `AgentAnalysis` rows; exposes `analyze()`, `council()`, `list_history()` |
| `backend/app/routers/agents.py` | 4 endpoints |
| `backend/app/models/agents.py` | `PersonaView`, `AnalysisRequest`, `AnalysisResponse`, `CouncilRequest`, `CouncilResponse`, `AnalysisHistoryResponse` |

### Modified files
| File | Change |
|---|---|
| `backend/app/db/tables.py` | Add `AgentAnalysis` table |
| `backend/app/db/__init__.py` | Re-export `AgentAnalysis` |
| `backend/app/models/__init__.py` | Re-export new agents API models |
| `backend/app/main.py` | Register `agents_router` |
| `backend/tests/test_openapi_parity.py` | Add 4 new routes |

### New tests
| Path | Coverage |
|---|---|
| `backend/tests/test_agents_personas.py` | All 6 personas register correctly + system prompt non-empty + Sentinel has the highest social_weight |
| `backend/tests/test_agents_context.py` | `AnalysisContext` build with mocked source data |
| `backend/tests/test_agents_analyzer.py` | Analyzer with stubbed LLM router → structured response shape |
| `backend/tests/test_agents_service.py` | `analyze()` persists row + returns dict; `council()` runs N personas; `list_history()` filters by symbol |
| `backend/tests/test_app_smoke.py` (append) | One smoke test per endpoint |

### Frontend
| File | Change |
|---|---|
| `frontend-v2/src/lib/api.js` | Add 4 new API client functions |
| `frontend-v2/src/pages/IntelligencePage.jsx` | Replace placeholder with real implementation |

### Untouched
- All Phase 0–6 work other than the listed adjustments.
- Frontend visual identity (steel blue palette).
- Strategy framework, broker, backtest, risk, observability.

---

## Pre-flight

- [ ] Confirm baseline (Phase 6 ends at 132 backend tests passing):
```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -q
```
Expected: **132 passed**.

- [ ] Branch off P6:
```bash
cd ~/NewBirdClaude
git checkout feat/frontend-v2
git checkout -b feat/p7-ai-council
```

---

## Task 1: Core agents framework — base types

**Goal:** Define the foundational types every other agent module depends on.

**Files:**
- Create: `backend/core/agents/__init__.py`
- Create: `backend/core/agents/base.py`

- [ ] **Step 1: `base.py`**

```python
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
class PersonaResponse:
    """Structured output of a single Analyzer.run() call."""

    persona_id: str
    symbol: str
    verdict: str  # "buy" | "hold" | "sell"
    confidence: float  # 0.0 - 1.0
    reasoning_summary: str
    key_factors: list[KeyFactor] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)
    raw_question: Optional[str] = None
    generated_at: Optional[datetime] = None
```

- [ ] **Step 2: `__init__.py` (placeholder; full re-exports in Task 6)**

```python
"""AI Council framework — persona-driven investment analysis."""
from __future__ import annotations

from core.agents.base import (
    KeyFactor,
    Persona,
    PersonaResponse,
    SignalWeights,
)

__all__ = ["KeyFactor", "Persona", "PersonaResponse", "SignalWeights"]
```

- [ ] **Step 3: Verify imports**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
python -c "
from core.agents import Persona, SignalWeights, KeyFactor, PersonaResponse
p = Persona(id='x', name='X', style='s', description='d', system_prompt='p')
print('ok', p.weights.as_dict())
"
```
Expected: `ok {'fundamentals': 0.5, 'news': 0.5, 'social': 0.5, 'technical': 0.5, 'macro': 0.5}`.

- [ ] **Step 4: Tests still pass**

```bash
pytest tests/ -q
```
Expected: **132 passed**.

- [ ] **Step 5: Commit**

```bash
git add backend/core/agents/
git commit -m "feat(agents): add Persona / SignalWeights / PersonaResponse base types"
```

---

## Task 2: Six built-in personas (TDD)

**Goal:** Define the 6 personas with hand-crafted system prompts and weight tunings.

**Files:**
- Create: `backend/core/agents/personas.py`
- Create: `backend/tests/test_agents_personas.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_agents_personas.py
"""All 6 built-in personas register and look right."""
from __future__ import annotations

import pytest

from core.agents.personas import (
    BUILTIN_PERSONAS,
    PERSONA_INDEX,
    get_persona,
)
from core.agents.base import Persona


EXPECTED_IDS = {"buffett", "graham", "lynch", "soros", "burry", "sentinel"}


def test_six_personas_registered() -> None:
    assert len(BUILTIN_PERSONAS) == 6
    assert {p.id for p in BUILTIN_PERSONAS} == EXPECTED_IDS


def test_each_persona_has_non_empty_system_prompt() -> None:
    for p in BUILTIN_PERSONAS:
        assert isinstance(p, Persona)
        assert len(p.system_prompt.strip()) > 200, f"{p.id} prompt too short"
        assert "JSON" in p.system_prompt or "json" in p.system_prompt, (
            f"{p.id} prompt should require JSON output"
        )


def test_sentinel_has_highest_social_weight() -> None:
    """Sentinel is our home-grown agent — designed to weight social heavily."""
    sentinel = get_persona("sentinel")
    others = [p for p in BUILTIN_PERSONAS if p.id != "sentinel"]
    max_other_social = max(p.weights.social for p in others)
    assert sentinel.weights.social >= max_other_social


def test_graham_has_lowest_social_weight() -> None:
    """Graham is strict-value purist — should ignore market noise entirely."""
    graham = get_persona("graham")
    assert graham.weights.social <= 0.1


def test_get_persona_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_persona("bogus_agent")


def test_persona_index_lookup() -> None:
    assert PERSONA_INDEX["buffett"].id == "buffett"
    assert PERSONA_INDEX["sentinel"].name.startswith("Trading Raven")
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_agents_personas.py -v
```
Expected: `ModuleNotFoundError: core.agents.personas`.

- [ ] **Step 3: Implement `personas.py`**

```python
# backend/core/agents/personas.py
"""Built-in personas with hand-crafted system prompts.

Each persona is a (style, weights, system_prompt) bundle. The system prompt
is what the LLM sees. It is structured to:
1. Anchor the LLM in the persona's voice
2. Specify the analysis style and what evidence to weigh
3. Mandate a strict JSON output schema (parsed by Analyzer)

Adding a new persona = append a Persona instance to BUILTIN_PERSONAS.
The shape of every system prompt is the same template (see _build_prompt)
to keep response parsing consistent.
"""
from __future__ import annotations

from core.agents.base import Persona, SignalWeights


# ---------------------------------------------------------------------------
# JSON output schema — every persona MUST return this shape so the analyzer
# can parse uniformly. Embedded into every system prompt below.
# ---------------------------------------------------------------------------

_OUTPUT_SCHEMA_HINT = """\
Return ONLY a single valid JSON object with this exact shape:

{
  "verdict": "buy" | "hold" | "sell",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning_summary": "<2-4 sentences explaining your call>",
  "key_factors": [
    {
      "signal": "fundamentals" | "news" | "social" | "technical" | "macro",
      "weight": <float between 0.0 and 1.0, how heavily this drove your call>,
      "interpretation": "<what you saw in this evidence>"
    },
    ... (3-6 items)
  ],
  "follow_up_questions": [
    "<question to deepen analysis>",
    ... (1-3 items)
  ]
}

Do NOT include markdown fences, explanatory prose outside the JSON, or any
other text. The first character of your response must be `{` and the last
must be `}`.
"""


def _build_prompt(persona_voice: str, weights: SignalWeights) -> str:
    """Compose a system prompt from a persona-specific voice block + the
    universal output-schema hint + a weights block."""
    weights_block = (
        f"Weight evidence in your reasoning roughly as follows:\n"
        f"- Fundamentals weight: {weights.fundamentals:.2f}\n"
        f"- News weight: {weights.news:.2f}\n"
        f"- Social-media sentiment weight: {weights.social:.2f}\n"
        f"- Technical / price action weight: {weights.technical:.2f}\n"
        f"- Macroeconomic context weight: {weights.macro:.2f}\n"
    )
    return f"""{persona_voice}

{weights_block}

You will be given a JSON context block describing a single security with
its current price action, fundamentals snapshot, recent news, social-
media signal aggregate, and the user's existing position (if any).
Optionally a user question follows. Reason step-by-step in your head, then
output your final structured verdict.

{_OUTPUT_SCHEMA_HINT}
"""


# ---------------------------------------------------------------------------
# Persona definitions
# ---------------------------------------------------------------------------

_BUFFETT_VOICE = """\
You are Warren Buffett. Speak in a calm, plain-spoken Midwestern voice with
the occasional folksy aphorism. Your investment lens is value with a focus
on durable competitive moats, predictable owner-earnings, capable management,
and an inviting margin of safety on price.

You favor businesses you would be comfortable owning entirely for ten years.
You distrust speculation, hype, complex derivatives, and stories that depend
on a greater fool. Short-term price action and social-media chatter are
mostly noise to you, though extreme euphoria can be a useful contrarian
warning.

Be honest about what you do not know. If a security is outside your
circle of competence (early-stage tech, biotech, crypto), say so plainly
and either pass or lean conservative.
"""

_GRAHAM_VOICE = """\
You are Benjamin Graham, the father of value investing. Your discipline is
strict and quantitative: you want a hard margin of safety relative to
asset value, defensive criteria on debt and earnings stability, and you
treat the market as a manic-depressive business partner whose moods you
can ignore.

You categorize every analysis as either "Defensive" (suitable for the
risk-averse investor) or "Enterprising" (acceptable to a more diligent
investor) and explain which class applies. You do NOT consider social
media or short-term news; the only signals that matter are price relative
to underlying value, balance-sheet quality, and earnings stability.
"""

_LYNCH_VOICE = """\
You are Peter Lynch — pragmatic, energetic, story-driven. Your edge is
seeing things on the ground before Wall Street notices. You categorize
companies into Slow Growers, Stalwarts, Fast Growers, Cyclicals, Turnarounds,
and Asset Plays, and you pick a category before pricing a verdict.

You like companies whose products you can describe in a sentence to a
twelve-year-old. You favor reasonable PE relative to growth (PEG), and
you watch what people actually use. Social-media chatter is a useful
ground-level signal — it tells you what consumers are excited about —
but never the final word; you want fundamentals to confirm the story.
"""

_SOROS_VOICE = """\
You are George Soros. Your central insight is reflexivity: market prices
not only reflect fundamentals but actively change them through feedback
loops. You hunt for self-reinforcing trends and fragile equilibria where
sentiment and fundamentals are diverging.

Macroeconomic regime, central-bank posture, currency flows, and political
risk are central to every read. You take social-media sentiment seriously
because it is a leading indicator of crowd narrative shifts, and you ask
where the crowd's beliefs could collide with reality. Your verdicts are
often medium-term and tactical, not long-term hold theses.
"""

_BURRY_VOICE = """\
You are Michael Burry. You are skeptical, contrarian, and obsessed with
finding what consensus is missing or refusing to see. You read 10-Ks line
by line, you watch capital cycles, and you think most bull markets contain
a bubble somewhere.

You assign extra weight to fundamental decay hidden in adjusted-EPS
narratives, to insider sales, and to euphoric social-media sentiment as
a tell that a position is crowded. A "sell" or "avoid" call against a
fashionable name is your most valuable output. When fundamentals are
genuinely cheap and consensus is fearful, you will buy decisively.
"""

_SENTINEL_VOICE = """\
You are Trading Raven Sentinel — a multi-source synthesis agent unique
to this platform. You are NOT a real human investor; you are an explicit
multi-signal aggregator. Your job is to make the cleanest possible
data-driven call by reading ALL the supplied evidence with no a-priori
style bias.

You give particularly heavy weight to the social-media signal aggregate
that the platform's P5 pipeline computes — that is your primary edge
because most agents overlook crowd narrative dynamics. You then cross-
check it against fundamentals, news flow, and price action. You will
explicitly note when signals disagree and decline to take a high-confidence
position without confluence.

Do not impersonate any human investor. Speak in concise, technical
analyst voice — section headers, numbers, and clear conclusions.
"""


BUILTIN_PERSONAS: list[Persona] = [
    Persona(
        id="buffett",
        name="Warren Buffett",
        style="value · moat · long-term",
        description="价值投资 / 护城河 / 长期持有 / 严格能力圈",
        weights=SignalWeights(fundamentals=0.95, news=0.40, social=0.05, technical=0.05, macro=0.30),
        system_prompt=_build_prompt(_BUFFETT_VOICE, SignalWeights(
            fundamentals=0.95, news=0.40, social=0.05, technical=0.05, macro=0.30,
        )),
    ),
    Persona(
        id="graham",
        name="Benjamin Graham",
        style="strict value · margin of safety",
        description="纯定量价值 / 资产负债表 / 安全边际",
        weights=SignalWeights(fundamentals=1.00, news=0.20, social=0.00, technical=0.00, macro=0.10),
        system_prompt=_build_prompt(_GRAHAM_VOICE, SignalWeights(
            fundamentals=1.00, news=0.20, social=0.00, technical=0.00, macro=0.10,
        )),
    ),
    Persona(
        id="lynch",
        name="Peter Lynch",
        style="story-driven · GARP",
        description="买你看得懂的 / PEG / 草根研究",
        weights=SignalWeights(fundamentals=0.70, news=0.55, social=0.55, technical=0.30, macro=0.20),
        system_prompt=_build_prompt(_LYNCH_VOICE, SignalWeights(
            fundamentals=0.70, news=0.55, social=0.55, technical=0.30, macro=0.20,
        )),
    ),
    Persona(
        id="soros",
        name="George Soros",
        style="reflexivity · macro · tactical",
        description="反身性 / 宏观周期 / 趋势 / 中期",
        weights=SignalWeights(fundamentals=0.40, news=0.80, social=0.65, technical=0.55, macro=0.95),
        system_prompt=_build_prompt(_SOROS_VOICE, SignalWeights(
            fundamentals=0.40, news=0.80, social=0.65, technical=0.55, macro=0.95,
        )),
    ),
    Persona(
        id="burry",
        name="Michael Burry",
        style="contrarian · bubble-hunter",
        description="反向 / 泡沫识别 / 隐藏基本面恶化",
        weights=SignalWeights(fundamentals=0.85, news=0.50, social=0.65, technical=0.40, macro=0.55),
        system_prompt=_build_prompt(_BURRY_VOICE, SignalWeights(
            fundamentals=0.85, news=0.50, social=0.65, technical=0.40, macro=0.55,
        )),
    ),
    Persona(
        id="sentinel",
        name="Trading Raven Sentinel",
        style="multi-signal synthesis · platform-native",
        description="舆情合成 / 多源融合 / 我们独有",
        weights=SignalWeights(fundamentals=0.55, news=0.65, social=0.95, technical=0.50, macro=0.45),
        system_prompt=_build_prompt(_SENTINEL_VOICE, SignalWeights(
            fundamentals=0.55, news=0.65, social=0.95, technical=0.50, macro=0.45,
        )),
    ),
]


PERSONA_INDEX: dict[str, Persona] = {p.id: p for p in BUILTIN_PERSONAS}


def get_persona(persona_id: str) -> Persona:
    """Look up a persona by id. Raises KeyError if not found."""
    if persona_id not in PERSONA_INDEX:
        raise KeyError(f"Unknown persona id: {persona_id!r}")
    return PERSONA_INDEX[persona_id]


def list_personas() -> list[Persona]:
    """Return the canonical persona list."""
    return list(BUILTIN_PERSONAS)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_agents_personas.py -v
```
Expected: 6 PASS.

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -q
```
Expected: **138 passed** (132 + 6).

- [ ] **Step 6: Commit**

```bash
git add backend/core/agents/personas.py backend/tests/test_agents_personas.py
git commit -m "feat(agents): add 6 built-in personas (Buffett/Graham/Lynch/Soros/Burry/Sentinel)"
```

---

## Task 3: Analysis context

**Goal:** Define the `AnalysisContext` value type the analyzer feeds to the LLM, plus an abstract `ContextBuilder` interface so different concrete builders (live data, mocked data, backtest data) can plug in.

**Files:**
- Create: `backend/core/agents/context.py`
- Create: `backend/tests/test_agents_context.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_agents_context.py
"""AnalysisContext value object + ContextBuilder ABC."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.agents.context import (
    AnalysisContext,
    ContextBuilder,
    NewsItem,
    PriceSnapshot,
    PositionSnapshot,
    SocialSignalSnapshot,
)


def test_analysis_context_to_json_block_contains_all_sections() -> None:
    ctx = AnalysisContext(
        symbol="NVDA",
        question="Should I add to my position?",
        price=PriceSnapshot(
            last=850.0, previous_close=820.0, change_pct=3.66,
            week_change_pct=5.2, month_change_pct=18.0, year_change_pct=180.0,
        ),
        fundamentals={"company_name": "NVIDIA", "sector": "Technology", "summary": "GPU leader"},
        recent_news=[
            NewsItem(title="NVDA beats earnings", summary="...", source="Tavily", at=datetime.now(timezone.utc)),
        ],
        social=SocialSignalSnapshot(
            social_score=0.71, market_score=0.55, final_weight=0.66,
            action="buy", confidence_label="high", reasons=["X buzz", "earnings beat"],
        ),
        position=PositionSnapshot(qty=10.0, avg_entry_price=800.0, market_value=8500.0, unrealized_pl=500.0),
        generated_at=datetime.now(timezone.utc),
    )
    block = ctx.to_json_block()
    parsed = json.loads(block)
    assert parsed["symbol"] == "NVDA"
    assert parsed["price"]["last"] == 850.0
    assert parsed["fundamentals"]["company_name"] == "NVIDIA"
    assert len(parsed["recent_news"]) == 1
    assert parsed["social"]["action"] == "buy"
    assert parsed["position"]["qty"] == 10.0


def test_analysis_context_handles_no_position() -> None:
    ctx = AnalysisContext(
        symbol="AAPL",
        question=None,
        price=PriceSnapshot(last=200.0, previous_close=200.0, change_pct=0.0, week_change_pct=0.0, month_change_pct=0.0, year_change_pct=0.0),
        fundamentals={},
        recent_news=[],
        social=None,
        position=None,
        generated_at=datetime.now(timezone.utc),
    )
    parsed = json.loads(ctx.to_json_block())
    assert parsed["position"] is None
    assert parsed["social"] is None


def test_context_builder_is_abstract() -> None:
    with pytest.raises(TypeError):
        ContextBuilder()  # type: ignore[abstract]
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_agents_context.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `context.py`**

```python
# backend/core/agents/context.py
"""AnalysisContext value object + ContextBuilder ABC.

The analyzer hands one of these to the LLM as a structured JSON block.
Building one requires reading our concrete data services (alpaca,
polygon, social_signal, etc.); that lives in app/services/agents_service.py.
This module only defines the shape and the abstract contract.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PriceSnapshot:
    last: float
    previous_close: float
    change_pct: float  # since previous close
    week_change_pct: float
    month_change_pct: float
    year_change_pct: float


@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    source: str
    at: datetime


@dataclass(frozen=True)
class SocialSignalSnapshot:
    """A read of P5's social-signal pipeline at the time of analysis."""

    social_score: float  # in [-1, 1]
    market_score: float  # in [-1, 1]
    final_weight: float  # in [-1, 1]
    action: str  # "buy" | "sell" | "hold" | "avoid"
    confidence_label: str  # "low" | "medium" | "high"
    reasons: list[str]


@dataclass(frozen=True)
class PositionSnapshot:
    qty: float
    avg_entry_price: float
    market_value: float
    unrealized_pl: float


@dataclass(frozen=True)
class AnalysisContext:
    """Everything the analyzer hands to the LLM, in one bundle."""

    symbol: str
    question: Optional[str]
    price: PriceSnapshot
    fundamentals: dict[str, object]
    recent_news: list[NewsItem]
    social: Optional[SocialSignalSnapshot]
    position: Optional[PositionSnapshot]
    generated_at: datetime

    def to_json_block(self) -> str:
        """Serialize to a stable JSON string for embedding in prompts."""
        payload: dict[str, object] = {
            "symbol": self.symbol,
            "question": self.question,
            "generated_at": self.generated_at.isoformat(),
            "price": asdict(self.price),
            "fundamentals": dict(self.fundamentals or {}),
            "recent_news": [
                {
                    "title": n.title,
                    "summary": n.summary,
                    "source": n.source,
                    "at": n.at.isoformat(),
                }
                for n in self.recent_news
            ],
            "social": asdict(self.social) if self.social is not None else None,
            "position": asdict(self.position) if self.position is not None else None,
        }
        return json.dumps(payload, ensure_ascii=False, default=str, indent=2)


class ContextBuilder(ABC):
    """Interface every concrete context builder implements.

    Concrete impls live outside `core/`. The framework only depends on
    the shape, not on alpaca/polygon/etc.
    """

    @abstractmethod
    async def build(self, symbol: str, *, question: Optional[str] = None) -> AnalysisContext:
        """Gather all evidence for `symbol` and assemble an AnalysisContext."""
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_agents_context.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -q
```
Expected: **141 passed**.

- [ ] **Step 6: Commit**

```bash
git add backend/core/agents/context.py backend/tests/test_agents_context.py
git commit -m "feat(agents): add AnalysisContext + ContextBuilder ABC"
```

---

## Task 4: LLM router (OpenAI-first)

**Goal:** Wrap an LLM call behind a small, swappable interface so the analyzer is provider-agnostic. Phase 7 implements one driver: OpenAI structured-output JSON mode.

**Files:**
- Create: `backend/core/agents/llm_router.py`

- [ ] **Step 1: Write `llm_router.py`**

```python
# backend/core/agents/llm_router.py
"""LLM router — abstract single-shot text completion + concrete OpenAI driver.

Stays thin on purpose. Streaming, tool calling, and multi-turn chat are
NOT in scope; we are doing one structured JSON request per analysis.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class LLMRouterError(RuntimeError):
    """Generic LLM call failure (network, parsing, rate limit)."""


class LLMRouterUnavailableError(LLMRouterError):
    """Raised when no provider is configured (e.g. no OPENAI_API_KEY)."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class LLMRouter(ABC):
    """Abstract single-shot text generator.

    Concrete implementations call the chosen provider with the supplied
    system + user prompt and return the raw text (expected to be JSON
    when the system prompt asks for it; the analyzer parses).
    """

    @abstractmethod
    async def generate(self, *, system: str, user: str, model: Optional[str] = None) -> LLMResponse:
        """Generate a single response. Raise LLMRouterError on failure."""


class OpenAILLMRouter(LLMRouter):
    """OpenAI driver. Uses gpt-4o-mini by default for cost; bump to gpt-4o
    via the `model` arg when accuracy matters more than latency.

    Reads the API key from `runtime_settings.get_setting('OPENAI_API_KEY')`.
    """

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, *, default_model: Optional[str] = None) -> None:
        self._default_model = default_model or self.DEFAULT_MODEL

    async def generate(self, *, system: str, user: str, model: Optional[str] = None) -> LLMResponse:
        api_key = self._resolve_api_key()
        if not api_key:
            raise LLMRouterUnavailableError(
                "OPENAI_API_KEY is not configured. Set it under Settings."
            )

        # Lazy import so test code that monkeypatches doesn't need the
        # SDK installed.
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise LLMRouterError(f"openai SDK not installed: {exc}") from exc

        client = AsyncOpenAI(api_key=api_key)
        model_id = model or self._default_model

        try:
            completion = await client.chat.completions.create(
                model=model_id,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.4,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMRouterError(f"OpenAI call failed: {exc}") from exc

        choice = completion.choices[0]
        text = choice.message.content or ""
        if not text.strip():
            raise LLMRouterError("OpenAI returned empty content")

        usage = getattr(completion, "usage", None)
        return LLMResponse(
            text=text,
            model=completion.model or model_id,
            tokens_in=getattr(usage, "prompt_tokens", None),
            tokens_out=getattr(usage, "completion_tokens", None),
        )

    @staticmethod
    def _resolve_api_key() -> Optional[str]:
        # Lazy import to avoid a circular dep at module load.
        from app import runtime_settings

        return runtime_settings.get_setting("OPENAI_API_KEY")
```

- [ ] **Step 2: Smoke import**

```bash
python -c "
from core.agents.llm_router import LLMRouter, OpenAILLMRouter, LLMRouterError, LLMRouterUnavailableError
print('ok', OpenAILLMRouter.DEFAULT_MODEL)
"
```
Expected: `ok gpt-4o-mini`.

- [ ] **Step 3: Tests still pass**

```bash
pytest tests/ -q
```
Expected: **141 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/agents/llm_router.py
git commit -m "feat(agents): add LLMRouter ABC + OpenAI driver"
```

---

## Task 5: Analyzer orchestrator (TDD)

**Goal:** Glue persona + context + LLM into one `Analyzer.run()` call that returns a parsed `PersonaResponse`.

**Files:**
- Create: `backend/core/agents/analyzer.py`
- Create: `backend/tests/test_agents_analyzer.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_agents_analyzer.py
"""Analyzer composes persona + ctx + LLM and parses structured output."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.agents.analyzer import Analyzer, AnalyzerParseError
from core.agents.context import AnalysisContext, PriceSnapshot
from core.agents.llm_router import LLMResponse, LLMRouter, LLMRouterError
from core.agents.personas import get_persona


class _StubLLMRouter(LLMRouter):
    def __init__(self, payload: str | Exception) -> None:
        self.payload = payload
        self.last_system: str = ""
        self.last_user: str = ""

    async def generate(self, *, system: str, user: str, model=None):
        self.last_system = system
        self.last_user = user
        if isinstance(self.payload, Exception):
            raise self.payload
        return LLMResponse(text=self.payload, model="stub")


def _ctx() -> AnalysisContext:
    return AnalysisContext(
        symbol="NVDA",
        question=None,
        price=PriceSnapshot(
            last=850.0, previous_close=820.0,
            change_pct=3.66, week_change_pct=5.2, month_change_pct=18.0, year_change_pct=180.0,
        ),
        fundamentals={"company_name": "NVIDIA"},
        recent_news=[],
        social=None,
        position=None,
        generated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_analyzer_parses_structured_response() -> None:
    payload = json.dumps({
        "verdict": "buy",
        "confidence": 0.7,
        "reasoning_summary": "Earnings momentum.",
        "key_factors": [
            {"signal": "fundamentals", "weight": 0.6, "interpretation": "Beat estimates."},
            {"signal": "social", "weight": 0.4, "interpretation": "Crowd is excited."},
        ],
        "follow_up_questions": ["What is the FCF outlook?"],
    })
    router = _StubLLMRouter(payload)
    analyzer = Analyzer(router=router)
    response = await analyzer.run(persona=get_persona("buffett"), ctx=_ctx())
    assert response.persona_id == "buffett"
    assert response.verdict == "buy"
    assert response.confidence == 0.7
    assert len(response.key_factors) == 2
    assert response.key_factors[0].signal == "fundamentals"
    assert response.follow_up_questions == ["What is the FCF outlook?"]


@pytest.mark.asyncio
async def test_analyzer_passes_persona_system_prompt_to_router() -> None:
    payload = json.dumps({
        "verdict": "hold", "confidence": 0.5, "reasoning_summary": "x",
        "key_factors": [], "follow_up_questions": [],
    })
    router = _StubLLMRouter(payload)
    analyzer = Analyzer(router=router)
    persona = get_persona("graham")
    await analyzer.run(persona=persona, ctx=_ctx())
    assert "Benjamin Graham" in router.last_system
    assert "NVDA" in router.last_user


@pytest.mark.asyncio
async def test_analyzer_rejects_invalid_verdict() -> None:
    payload = json.dumps({
        "verdict": "BUY_LOTS", "confidence": 0.7, "reasoning_summary": "x",
        "key_factors": [], "follow_up_questions": [],
    })
    router = _StubLLMRouter(payload)
    analyzer = Analyzer(router=router)
    with pytest.raises(AnalyzerParseError):
        await analyzer.run(persona=get_persona("buffett"), ctx=_ctx())


@pytest.mark.asyncio
async def test_analyzer_rejects_non_json() -> None:
    router = _StubLLMRouter("not actually json")
    analyzer = Analyzer(router=router)
    with pytest.raises(AnalyzerParseError):
        await analyzer.run(persona=get_persona("buffett"), ctx=_ctx())


@pytest.mark.asyncio
async def test_analyzer_propagates_router_error() -> None:
    router = _StubLLMRouter(LLMRouterError("rate limited"))
    analyzer = Analyzer(router=router)
    with pytest.raises(LLMRouterError):
        await analyzer.run(persona=get_persona("buffett"), ctx=_ctx())
```

- [ ] **Step 2: Run, verify failure**

```bash
pytest tests/test_agents_analyzer.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `analyzer.py`**

```python
# backend/core/agents/analyzer.py
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
    def _parse_response(*, persona: Persona, ctx: AnalysisContext, raw_text: str) -> PersonaResponse:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise AnalyzerParseError(f"Response is not valid JSON: {exc}\nRaw text: {raw_text[:300]}") from exc

        verdict = str(payload.get("verdict", "")).lower().strip()
        if verdict not in VALID_VERDICTS:
            raise AnalyzerParseError(f"Invalid verdict {verdict!r}, expected one of {sorted(VALID_VERDICTS)}")

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
        follow_up = [str(q).strip() for q in follow_up_raw if isinstance(q, (str, int, float)) and str(q).strip()]

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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_agents_analyzer.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -q
```
Expected: **146 passed**.

- [ ] **Step 6: Commit**

```bash
git add backend/core/agents/analyzer.py backend/tests/test_agents_analyzer.py
git commit -m "feat(agents): add Analyzer orchestrator with strict JSON parsing"
```

---

## Task 6: Finalize public API + update __init__.py

**Files:**
- Modify: `backend/core/agents/__init__.py`

- [ ] **Step 1: Replace `__init__.py` contents**

```python
"""AI Council framework — persona-driven investment analysis.

Public API:
    Persona, SignalWeights, KeyFactor, PersonaResponse
    AnalysisContext, ContextBuilder, PriceSnapshot, NewsItem,
        SocialSignalSnapshot, PositionSnapshot
    LLMRouter, OpenAILLMRouter, LLMResponse, LLMRouterError, LLMRouterUnavailableError
    Analyzer, AnalyzerParseError
    BUILTIN_PERSONAS, PERSONA_INDEX, get_persona, list_personas
"""
from __future__ import annotations

from core.agents.analyzer import Analyzer, AnalyzerParseError
from core.agents.base import KeyFactor, Persona, PersonaResponse, SignalWeights
from core.agents.context import (
    AnalysisContext,
    ContextBuilder,
    NewsItem,
    PositionSnapshot,
    PriceSnapshot,
    SocialSignalSnapshot,
)
from core.agents.llm_router import (
    LLMResponse,
    LLMRouter,
    LLMRouterError,
    LLMRouterUnavailableError,
    OpenAILLMRouter,
)
from core.agents.personas import (
    BUILTIN_PERSONAS,
    PERSONA_INDEX,
    get_persona,
    list_personas,
)

__all__ = [
    "AnalysisContext",
    "Analyzer",
    "AnalyzerParseError",
    "BUILTIN_PERSONAS",
    "ContextBuilder",
    "KeyFactor",
    "LLMResponse",
    "LLMRouter",
    "LLMRouterError",
    "LLMRouterUnavailableError",
    "NewsItem",
    "OpenAILLMRouter",
    "PERSONA_INDEX",
    "Persona",
    "PersonaResponse",
    "PositionSnapshot",
    "PriceSnapshot",
    "SignalWeights",
    "SocialSignalSnapshot",
    "get_persona",
    "list_personas",
]
```

- [ ] **Step 2: Smoke import**

```bash
python -c "
from core.agents import (
    Analyzer, BUILTIN_PERSONAS, OpenAILLMRouter, get_persona, AnalysisContext,
)
print('ok', len(BUILTIN_PERSONAS))
"
```
Expected: `ok 6`.

- [ ] **Step 3: Tests pass**

```bash
pytest tests/ -q
```
Expected: **146 passed**.

- [ ] **Step 4: Commit**

```bash
git add backend/core/agents/__init__.py
git commit -m "feat(agents): expose framework public API"
```

---

## Task 7: DB table + agents service (concrete ContextBuilder)

**Goal:** Persist analyses in `AgentAnalysis` and provide the live `ContextBuilder` that pulls from our existing services (alpaca, polygon, chart, company, news, social_signal).

**Files:**
- Modify: `backend/app/db/tables.py` (append AgentAnalysis)
- Modify: `backend/app/db/__init__.py` (re-export)
- Create: `backend/app/services/agents_service.py`
- Create: `backend/tests/test_agents_service.py`

- [ ] **Step 1: Append `AgentAnalysis` to `app/db/tables.py`**

```python


class AgentAnalysis(Base):
    """One persisted analysis per (persona, symbol, timestamp)."""

    __tablename__ = "agent_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    persona_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verdict: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_factors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    follow_up_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
```

Update `backend/app/db/__init__.py`: add `AgentAnalysis` to imports + `__all__` alphabetically.

- [ ] **Step 2: Failing service test**

```python
# backend/tests/test_agents_service.py
"""agents_service.analyze() persists rows + returns dict."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

from app.database import AsyncSessionLocal, AgentAnalysis, init_database


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    from app.db import engine as engine_module
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    db_path = tmp_path / "agents.db"
    new_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, future=True)
    factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", factory)
    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    await new_engine.dispose()


@pytest.mark.asyncio
async def test_analyze_persists_row_and_returns_dict() -> None:
    from app.services import agents_service

    fake_response = {
        "verdict": "buy",
        "confidence": 0.72,
        "reasoning_summary": "Strong moat.",
        "key_factors": [{"signal": "fundamentals", "weight": 0.7, "interpretation": "Beat."}],
        "follow_up_questions": ["What about competition?"],
    }

    async def fake_generate(*, system, user, model=None):
        from core.agents.llm_router import LLMResponse
        return LLMResponse(text=json.dumps(fake_response), model="stub-1")

    async def fake_build(self, symbol, *, question=None):
        from core.agents.context import AnalysisContext, PriceSnapshot
        return AnalysisContext(
            symbol=symbol, question=question,
            price=PriceSnapshot(
                last=100.0, previous_close=98.0,
                change_pct=2.0, week_change_pct=3.0, month_change_pct=5.0, year_change_pct=10.0,
            ),
            fundamentals={"company_name": symbol},
            recent_news=[], social=None, position=None,
            generated_at=datetime.now(timezone.utc),
        )

    with patch("core.agents.OpenAILLMRouter.generate", new=fake_generate), \
         patch.object(agents_service.LiveContextBuilder, "build", new=fake_build):
        async with AsyncSessionLocal() as session:
            result = await agents_service.analyze(
                session, persona_id="buffett", symbol="AAPL", question=None,
            )
            assert result["persona_id"] == "buffett"
            assert result["verdict"] == "buy"
            assert result["confidence"] == 0.72
            assert "Strong moat" in result["reasoning_summary"]

            from sqlalchemy import select
            rows = (await session.execute(select(AgentAnalysis))).scalars().all()
            assert len(rows) == 1
            assert rows[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_council_runs_multiple_personas() -> None:
    from app.services import agents_service

    async def fake_generate(*, system, user, model=None):
        from core.agents.llm_router import LLMResponse
        return LLMResponse(
            text=json.dumps({
                "verdict": "hold", "confidence": 0.6, "reasoning_summary": "neutral",
                "key_factors": [], "follow_up_questions": [],
            }),
            model="stub",
        )

    async def fake_build(self, symbol, *, question=None):
        from core.agents.context import AnalysisContext, PriceSnapshot
        return AnalysisContext(
            symbol=symbol, question=question,
            price=PriceSnapshot(
                last=100.0, previous_close=100.0,
                change_pct=0.0, week_change_pct=0.0, month_change_pct=0.0, year_change_pct=0.0,
            ),
            fundamentals={}, recent_news=[], social=None, position=None,
            generated_at=datetime.now(timezone.utc),
        )

    with patch("core.agents.OpenAILLMRouter.generate", new=fake_generate), \
         patch.object(agents_service.LiveContextBuilder, "build", new=fake_build):
        async with AsyncSessionLocal() as session:
            result = await agents_service.council(
                session,
                persona_ids=["buffett", "graham", "sentinel"],
                symbol="MSFT",
                question="Long-term hold?",
            )
            assert len(result["analyses"]) == 3
            assert {a["persona_id"] for a in result["analyses"]} == {"buffett", "graham", "sentinel"}


@pytest.mark.asyncio
async def test_list_history_filters_by_symbol() -> None:
    from app.services import agents_service

    async with AsyncSessionLocal() as session:
        for symbol, persona in [("AAPL", "buffett"), ("AAPL", "graham"), ("MSFT", "buffett")]:
            session.add(AgentAnalysis(
                persona_id=persona, symbol=symbol, verdict="buy", confidence=0.7,
                reasoning_summary="x",
            ))
        await session.commit()
        rows = await agents_service.list_history(session, symbol="AAPL", limit=20)
        assert len(rows) == 2
        assert all(r["symbol"] == "AAPL" for r in rows)
```

- [ ] **Step 3: Implement `agents_service.py`**

```python
# backend/app/services/agents_service.py
"""Concrete glue between the agents framework and our data services.

Owns:
- LiveContextBuilder — pulls price, fundamentals, news, social signal,
  position from existing services.
- analyze(), council(), list_history() — public surface for the router.
- Persistence into AgentAnalysis.

Stays slim by delegating heavy lifting to core/agents/*.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AgentAnalysis
from app.services import (
    alpaca_service,
    chart_service,
    company_profile_service,
    market_research_service,
    polygon_service,
    social_signal_service,
)
from core.agents import (
    AnalysisContext,
    Analyzer,
    ContextBuilder,
    NewsItem,
    OpenAILLMRouter,
    PersonaResponse,
    PositionSnapshot,
    PriceSnapshot,
    SocialSignalSnapshot,
    get_persona,
    list_personas,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live context builder
# ---------------------------------------------------------------------------


class LiveContextBuilder(ContextBuilder):
    """Production ContextBuilder — reads from real services.

    Each source is wrapped in `_safe_call` so a flaky external API never
    blocks the analysis. Missing pieces become None / empty in the
    AnalysisContext, and the LLM is told there is no data for that channel.
    """

    async def build(self, symbol: str, *, question: Optional[str] = None) -> AnalysisContext:
        symbol = symbol.upper()
        price = await self._build_price(symbol)
        fundamentals = await self._build_fundamentals(symbol)
        recent_news = await self._build_news(symbol)
        social = await self._build_social(symbol)
        position = await self._build_position(symbol)

        return AnalysisContext(
            symbol=symbol,
            question=question,
            price=price,
            fundamentals=fundamentals,
            recent_news=recent_news,
            social=social,
            position=position,
            generated_at=datetime.now(timezone.utc),
        )

    async def _build_price(self, symbol: str) -> PriceSnapshot:
        last = 0.0
        previous_close = 0.0
        try:
            previous_close = float(await polygon_service.get_previous_close(symbol))
        except Exception as exc:
            logger.debug("polygon previous close failed for %s: %s", symbol, exc)

        chart_points: list[dict[str, Any]] = []
        try:
            chart = await chart_service.get_chart(symbol, range="3m")
            chart_points = list((chart or {}).get("points") or [])
        except Exception as exc:
            logger.debug("chart failed for %s: %s", symbol, exc)

        if chart_points:
            last = float(chart_points[-1].get("close") or chart_points[-1].get("price") or 0.0)
        if last == 0.0 and previous_close > 0.0:
            last = previous_close

        change_pct = self._pct(last, previous_close)
        week = self._lookback_pct(chart_points, 5)
        month = self._lookback_pct(chart_points, 22)
        year = self._lookback_pct(chart_points, 252)

        return PriceSnapshot(
            last=last,
            previous_close=previous_close or last,
            change_pct=change_pct,
            week_change_pct=week,
            month_change_pct=month,
            year_change_pct=year,
        )

    async def _build_fundamentals(self, symbol: str) -> dict[str, object]:
        try:
            profile = await company_profile_service.get_company_profile(symbol)
            if profile is None:
                return {}
            if hasattr(profile, "model_dump"):
                profile = profile.model_dump()
            return {
                "company_name": profile.get("company_name") or profile.get("name"),
                "sector": profile.get("sector"),
                "industry": profile.get("industry"),
                "summary": profile.get("business_summary") or profile.get("summary"),
                "market_cap": profile.get("market_cap"),
                "pe_ratio": profile.get("pe_ratio"),
            }
        except Exception as exc:
            logger.debug("fundamentals failed for %s: %s", symbol, exc)
            return {}

    async def _build_news(self, symbol: str) -> list[NewsItem]:
        try:
            payload = await market_research_service.get_news(symbol)
        except Exception as exc:
            logger.debug("news failed for %s: %s", symbol, exc)
            return []
        if payload is None:
            return []
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()
        items_raw = payload.get("items") or []
        if not items_raw and payload.get("summary"):
            items_raw = [{
                "title": payload.get("title") or symbol,
                "summary": payload.get("summary"),
                "source": payload.get("source") or "Tavily",
                "at": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            }]
        result: list[NewsItem] = []
        for item in items_raw[:5]:
            try:
                at_value = item.get("at") or item.get("timestamp") or datetime.now(timezone.utc).isoformat()
                if isinstance(at_value, str):
                    at = datetime.fromisoformat(at_value.replace("Z", "+00:00"))
                else:
                    at = at_value
                result.append(NewsItem(
                    title=str(item.get("title") or "")[:200],
                    summary=str(item.get("summary") or item.get("content") or "")[:500],
                    source=str(item.get("source") or "Tavily"),
                    at=at if at.tzinfo else at.replace(tzinfo=timezone.utc),
                ))
            except Exception as exc:
                logger.debug("news item parse failed: %s", exc)
        return result

    async def _build_social(self, symbol: str) -> Optional[SocialSignalSnapshot]:
        try:
            snapshot = await social_signal_service.score_symbol_signal(symbol)
        except Exception as exc:
            logger.debug("social signal failed for %s: %s", symbol, exc)
            return None
        if snapshot is None:
            return None
        if hasattr(snapshot, "model_dump"):
            snapshot = snapshot.model_dump()
        try:
            return SocialSignalSnapshot(
                social_score=float(snapshot.get("social_score") or 0.0),
                market_score=float(snapshot.get("market_score") or 0.0),
                final_weight=float(snapshot.get("final_weight") or 0.0),
                action=str(snapshot.get("action") or "hold"),
                confidence_label=str(snapshot.get("confidence_label") or "low"),
                reasons=list(snapshot.get("reasons") or [])[:5],
            )
        except (TypeError, ValueError):
            return None

    async def _build_position(self, symbol: str) -> Optional[PositionSnapshot]:
        try:
            positions = await alpaca_service.list_positions()
        except Exception as exc:
            logger.debug("positions failed for %s: %s", symbol, exc)
            return None
        for pos in positions or []:
            if str(pos.get("symbol", "")).upper() == symbol:
                try:
                    qty = float(pos.get("qty") or 0)
                    entry = float(pos.get("avg_entry_price") or pos.get("entry_price") or 0)
                    current = float(pos.get("current_price") or entry)
                    mv = float(pos.get("market_value") or qty * current)
                    upl = float(pos.get("unrealized_pl") or (current - entry) * qty)
                    return PositionSnapshot(qty=qty, avg_entry_price=entry, market_value=mv, unrealized_pl=upl)
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def _pct(curr: float, prev: float) -> float:
        if prev <= 0 or curr <= 0:
            return 0.0
        return ((curr - prev) / prev) * 100.0

    @staticmethod
    def _lookback_pct(points: list[dict[str, Any]], lookback: int) -> float:
        if len(points) < 2:
            return 0.0
        idx = max(0, len(points) - 1 - lookback)
        try:
            past = float(points[idx].get("close") or points[idx].get("price") or 0.0)
            now = float(points[-1].get("close") or points[-1].get("price") or 0.0)
            if past <= 0 or now <= 0:
                return 0.0
            return ((now - past) / past) * 100.0
        except (TypeError, ValueError):
            return 0.0


# ---------------------------------------------------------------------------
# Public service entry points
# ---------------------------------------------------------------------------


def list_personas_view() -> list[dict[str, object]]:
    return [p.public_view() for p in list_personas()]


async def analyze(
    session: AsyncSession,
    *,
    persona_id: str,
    symbol: str,
    question: Optional[str] = None,
    model: Optional[str] = None,
    builder: Optional[ContextBuilder] = None,
    router: Optional[Any] = None,
) -> dict[str, Any]:
    persona = get_persona(persona_id)
    builder = builder or LiveContextBuilder()
    router = router or OpenAILLMRouter()
    analyzer = Analyzer(router=router)

    ctx = await builder.build(symbol, question=question)
    response = await analyzer.run(persona=persona, ctx=ctx, model=model)

    row = AgentAnalysis(
        persona_id=response.persona_id,
        symbol=response.symbol,
        question=question or "",
        verdict=response.verdict,
        confidence=response.confidence,
        reasoning_summary=response.reasoning_summary,
        key_factors_json=json.dumps([asdict(k) for k in response.key_factors]),
        follow_up_json=json.dumps(response.follow_up_questions),
        context_json=ctx.to_json_block(),
        model=model or "",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _serialize(row, response)


async def council(
    session: AsyncSession,
    *,
    persona_ids: Iterable[str],
    symbol: str,
    question: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Run multiple personas against the same symbol.

    The context is built ONCE and reused across personas — saves N-1 round
    trips to alpaca/polygon/etc.
    """
    persona_ids = list(persona_ids)
    if not persona_ids:
        raise ValueError("persona_ids must not be empty")

    builder = LiveContextBuilder()
    ctx = await builder.build(symbol, question=question)
    router = OpenAILLMRouter()
    analyzer = Analyzer(router=router)

    analyses: list[dict[str, Any]] = []
    for pid in persona_ids:
        persona = get_persona(pid)
        response = await analyzer.run(persona=persona, ctx=ctx, model=model)
        row = AgentAnalysis(
            persona_id=response.persona_id,
            symbol=response.symbol,
            question=question or "",
            verdict=response.verdict,
            confidence=response.confidence,
            reasoning_summary=response.reasoning_summary,
            key_factors_json=json.dumps([asdict(k) for k in response.key_factors]),
            follow_up_json=json.dumps(response.follow_up_questions),
            context_json=ctx.to_json_block(),
            model=model or "",
        )
        session.add(row)
        await session.flush()
        analyses.append(_serialize(row, response))
    await session.commit()
    return {"symbol": symbol, "analyses": analyses}


async def list_history(
    session: AsyncSession,
    *,
    symbol: Optional[str] = None,
    persona_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = select(AgentAnalysis).order_by(desc(AgentAnalysis.id))
    if symbol:
        stmt = stmt.where(AgentAnalysis.symbol == symbol.upper())
    if persona_id:
        stmt = stmt.where(AgentAnalysis.persona_id == persona_id)
    stmt = stmt.limit(max(1, min(limit, 200)))
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize(row: AgentAnalysis, response: PersonaResponse) -> dict[str, Any]:
    return {
        "id": row.id,
        "persona_id": response.persona_id,
        "symbol": response.symbol,
        "question": response.raw_question,
        "verdict": response.verdict,
        "confidence": response.confidence,
        "reasoning_summary": response.reasoning_summary,
        "key_factors": [asdict(k) for k in response.key_factors],
        "follow_up_questions": list(response.follow_up_questions),
        "model": row.model,
        "created_at": row.created_at,
    }


def _serialize_row(row: AgentAnalysis) -> dict[str, Any]:
    try:
        key_factors = json.loads(row.key_factors_json or "[]")
    except json.JSONDecodeError:
        key_factors = []
    try:
        follow_up = json.loads(row.follow_up_json or "[]")
    except json.JSONDecodeError:
        follow_up = []
    return {
        "id": row.id,
        "persona_id": row.persona_id,
        "symbol": row.symbol,
        "question": row.question,
        "verdict": row.verdict,
        "confidence": row.confidence,
        "reasoning_summary": row.reasoning_summary,
        "key_factors": key_factors,
        "follow_up_questions": follow_up,
        "model": row.model,
        "created_at": row.created_at,
    }
```

- [ ] **Step 4: Run service tests**

```bash
pytest tests/test_agents_service.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Full suite**

```bash
pytest tests/ -q
```
Expected: **149 passed** (146 + 3).

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/tables.py backend/app/db/__init__.py backend/app/services/agents_service.py backend/tests/test_agents_service.py
git commit -m "feat(agents): add AgentAnalysis table + LiveContextBuilder + agents_service"
```

---

## Task 8: API models + router

**Files:**
- Create: `backend/app/models/agents.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/app/routers/agents.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_app_smoke.py`
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: API models**

```python
# backend/app/models/agents.py
"""AI Council API models."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PersonaWeightsView(BaseModel):
    fundamentals: float
    news: float
    social: float
    technical: float
    macro: float


class PersonaView(BaseModel):
    id: str
    name: str
    style: str
    description: str
    weights: PersonaWeightsView


class PersonasResponse(BaseModel):
    items: list[PersonaView]


class AnalysisRequest(BaseModel):
    persona_id: str
    symbol: str
    question: Optional[str] = None
    model: Optional[str] = None


class CouncilRequest(BaseModel):
    persona_ids: list[str] = Field(..., min_length=1)
    symbol: str
    question: Optional[str] = None
    model: Optional[str] = None


class KeyFactorView(BaseModel):
    signal: str
    weight: float
    interpretation: str


class AnalysisView(BaseModel):
    id: int
    persona_id: str
    symbol: str
    question: Optional[str] = None
    verdict: str
    confidence: float
    reasoning_summary: str
    key_factors: list[KeyFactorView] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    model: str = ""
    created_at: datetime


class CouncilResponse(BaseModel):
    symbol: str
    analyses: list[AnalysisView]


class AnalysisHistoryResponse(BaseModel):
    items: list[AnalysisView]
```

Update `app/models/__init__.py`: import + re-export `AnalysisHistoryResponse`, `AnalysisRequest`, `AnalysisView`, `CouncilRequest`, `CouncilResponse`, `KeyFactorView`, `PersonaView`, `PersonaWeightsView`, `PersonasResponse`. Append all to `__all__` alphabetically.

- [ ] **Step 2: Router**

```python
# backend/app/routers/agents.py
"""AI Council endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    AnalysisHistoryResponse,
    AnalysisRequest,
    AnalysisView,
    CouncilRequest,
    CouncilResponse,
    PersonasResponse,
    PersonaView,
)
from app.services import agents_service
from core.agents import LLMRouterUnavailableError

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/personas", response_model=PersonasResponse)
async def list_personas() -> PersonasResponse:
    return PersonasResponse(items=[PersonaView(**p) for p in agents_service.list_personas_view()])


@router.post("/analyze", response_model=AnalysisView)
async def analyze(request: AnalysisRequest, session: SessionDep) -> AnalysisView:
    try:
        result = await agents_service.analyze(
            session,
            persona_id=request.persona_id,
            symbol=request.symbol,
            question=request.question,
            model=request.model,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown persona: {exc}") from exc
    except LLMRouterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return AnalysisView(**result)


@router.post("/council", response_model=CouncilResponse)
async def council(request: CouncilRequest, session: SessionDep) -> CouncilResponse:
    try:
        result = await agents_service.council(
            session,
            persona_ids=request.persona_ids,
            symbol=request.symbol,
            question=request.question,
            model=request.model,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown persona: {exc}") from exc
    except LLMRouterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return CouncilResponse(
        symbol=result["symbol"],
        analyses=[AnalysisView(**a) for a in result["analyses"]],
    )


@router.get("/history", response_model=AnalysisHistoryResponse)
async def list_history(
    session: SessionDep,
    symbol: str | None = None,
    persona_id: str | None = None,
    limit: int = 50,
) -> AnalysisHistoryResponse:
    try:
        rows = await agents_service.list_history(
            session, symbol=symbol, persona_id=persona_id, limit=limit,
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return AnalysisHistoryResponse(items=[AnalysisView(**r) for r in rows])
```

- [ ] **Step 3: Register in `main.py`**

In `backend/app/main.py`:
- Add `from app.routers import agents as agents_router` near other router imports.
- Add `app.include_router(agents_router.router)` next to the registration block.

- [ ] **Step 4: Smoke tests**

Append to `backend/tests/test_app_smoke.py`:

```python


def test_agents_personas_endpoint(client) -> None:
    response = client.get("/api/agents/personas")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    ids = [p["id"] for p in body["items"]]
    assert {"buffett", "graham", "lynch", "soros", "burry", "sentinel"} <= set(ids)


def test_agents_history_endpoint(client) -> None:
    response = client.get("/api/agents/history")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
```

- [ ] **Step 5: Update parity test**

In `backend/tests/test_openapi_parity.py`, add 4 new routes alphabetically:
```python
("GET",    "/api/agents/history"),
("GET",    "/api/agents/personas"),
("POST",   "/api/agents/analyze"),
("POST",   "/api/agents/council"),
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/ -q
```
Expected: **151 passed** (149 + 2 smoke).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/agents.py backend/app/models/__init__.py backend/app/routers/agents.py backend/app/main.py backend/tests/test_app_smoke.py backend/tests/test_openapi_parity.py
git commit -m "feat(api): AI Council endpoints (personas / analyze / council / history)"
```

---

## Task 9: Frontend — IntelligencePage real implementation

**Files:**
- Modify: `frontend-v2/src/lib/api.js`
- Replace: `frontend-v2/src/pages/IntelligencePage.jsx`

- [ ] **Step 1: Add API client functions**

Append to `frontend-v2/src/lib/api.js`:

```javascript
// ----------------------------------------------------------- agents
export const listPersonas = () => request('/api/agents/personas');
export const analyzeWithPersona = (body) => request('/api/agents/analyze', { method: 'POST', body });
export const councilAnalyze = (body) => request('/api/agents/council', { method: 'POST', body });
export const listAgentHistory = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.symbol) qs.set('symbol', params.symbol);
  if (params.persona_id) qs.set('persona_id', params.persona_id);
  if (params.limit) qs.set('limit', String(params.limit));
  return request(`/api/agents/history${qs.toString() ? `?${qs}` : ''}`);
};
```

- [ ] **Step 2: Replace `IntelligencePage.jsx`**

Replace the entire file with a real implementation:

```jsx
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Sparkles, Users, History, Send, Check, AlertTriangle } from 'lucide-react';
import {
  listPersonas,
  analyzeWithPersona,
  councilAnalyze,
  listAgentHistory,
} from '../lib/api.js';
import {
  SectionHeader,
  LoadingState,
  ErrorState,
  EmptyState,
} from '../components/primitives.jsx';
import { ApiErrorBanner } from '../components/TopBar.jsx';
import { fmtRelativeTime, classNames } from '../lib/format.js';

const TABS = [
  { id: 'personas', label: 'Personas', icon: Sparkles },
  { id: 'council', label: 'Council', icon: Users },
  { id: 'history', label: 'History', icon: History },
];

export default function IntelligencePage() {
  const [tab, setTab] = useState('personas');

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="h-page">AI Council</h1>
          <p className="text-body-sm text-steel-200 mt-1">
            5 大师 + 1 Sentinel · 投资风格化分析(P7)· LLM 走 OpenAI · 上下文融合 P0–P5 全部数据
          </p>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex items-center gap-6 border-b border-steel-400">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={classNames(
              'h-10 -mb-px border-b-2 text-body-sm font-medium transition duration-150 inline-flex items-center gap-2 px-1',
              tab === t.id
                ? 'border-steel-500 text-steel-50'
                : 'border-transparent text-steel-200 hover:text-steel-50'
            )}
            onClick={() => setTab(t.id)}
          >
            <t.icon size={14} /> {t.label}
          </button>
        ))}
      </div>

      {tab === 'personas' && <SinglePersonaTab />}
      {tab === 'council' && <CouncilTab />}
      {tab === 'history' && <HistoryTab />}
    </div>
  );
}

// ---------------------------------------------------------- Persona picker

function PersonaCard({ persona, selected, onSelect }) {
  const isOurs = persona.id === 'sentinel';
  return (
    <button
      type="button"
      onClick={() => onSelect(persona.id)}
      className={classNames(
        'card-dense text-left card-hover relative',
        selected ? 'border-steel-500 shadow-focus' : '',
        isOurs ? 'bg-social-tint/10' : ''
      )}
    >
      {selected && <Check size={14} className="absolute top-2 right-2 text-steel-500" />}
      <div className="flex items-start justify-between mb-1">
        <div className="font-mono text-caption text-accent-silver">{persona.id}</div>
        {isOurs && <span className="pill-social">独家</span>}
      </div>
      <div className="text-body font-semibold text-steel-50 mb-1">{persona.name}</div>
      <div className="text-caption text-steel-200 mb-2">{persona.style}</div>
      <p className="text-body-sm text-steel-100 line-clamp-2">{persona.description}</p>
      <div className="mt-2 flex items-center gap-1 text-caption text-steel-300 tabular">
        Social {persona.weights.social.toFixed(2)} · Fund {persona.weights.fundamentals.toFixed(2)}
      </div>
    </button>
  );
}

// ---------------------------------------------------------- Single Persona

function SinglePersonaTab() {
  const queryClient = useQueryClient();
  const personasQ = useQuery({ queryKey: ['agent-personas'], queryFn: listPersonas });

  const [personaId, setPersonaId] = useState('buffett');
  const [symbol, setSymbol] = useState('NVDA');
  const [question, setQuestion] = useState('');

  const analyzeMut = useMutation({
    mutationFn: analyzeWithPersona,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-history'] }),
  });

  function submit(e) {
    e.preventDefault();
    if (!symbol.trim() || !personaId) return;
    analyzeMut.mutate({
      persona_id: personaId,
      symbol: symbol.trim().toUpperCase(),
      question: question.trim() || null,
    });
  }

  return (
    <div className="grid grid-cols-12 gap-6">
      <form onSubmit={submit} className="col-span-7 card space-y-5">
        <SectionHeader title="选 Persona + Symbol" subtitle="LLM 会综合 P0–P5 全部上下文给出风格化判断" />

        {personasQ.isLoading ? (
          <LoadingState rows={2} />
        ) : personasQ.isError ? (
          <ErrorState error={personasQ.error} onRetry={personasQ.refetch} />
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {(personasQ.data?.items || []).map((p) => (
              <PersonaCard
                key={p.id}
                persona={p}
                selected={personaId === p.id}
                onSelect={setPersonaId}
              />
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="h-caption block mb-2">Symbol</label>
            <input
              className="input uppercase"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            />
          </div>
        </div>

        <div>
          <label className="h-caption block mb-2">问题(可选)</label>
          <textarea
            className="input h-20"
            placeholder="例如:Should I add to my position given the recent earnings?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </div>

        {analyzeMut.isError && <ApiErrorBanner error={analyzeMut.error} label="分析失败" />}

        <button
          type="submit"
          className="btn-primary"
          disabled={analyzeMut.isPending || !symbol.trim()}
        >
          <Send size={14} /> {analyzeMut.isPending ? '分析中…' : '运行分析'}
        </button>
        <p className="text-caption text-steel-300">
          需要 Settings 里配置 OPENAI_API_KEY。每次约 1500-3000 tokens(gpt-4o-mini)。
        </p>
      </form>

      <div className="col-span-5">
        {analyzeMut.isPending && (
          <div className="card">
            <LoadingState rows={4} label="LLM 思考中…" />
          </div>
        )}
        {analyzeMut.data && <AnalysisResultCard analysis={analyzeMut.data} />}
        {!analyzeMut.data && !analyzeMut.isPending && (
          <div className="card">
            <EmptyState icon={Sparkles} title="尚未运行" hint="左侧选 persona + symbol 后提交。" />
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------- Council

function CouncilTab() {
  const queryClient = useQueryClient();
  const personasQ = useQuery({ queryKey: ['agent-personas'], queryFn: listPersonas });

  const [selected, setSelected] = useState(['buffett', 'graham', 'sentinel']);
  const [symbol, setSymbol] = useState('NVDA');
  const [question, setQuestion] = useState('');

  const councilMut = useMutation({
    mutationFn: councilAnalyze,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agent-history'] }),
  });

  function togglePersona(id) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  function submit(e) {
    e.preventDefault();
    if (!symbol.trim() || selected.length === 0) return;
    councilMut.mutate({
      persona_ids: selected,
      symbol: symbol.trim().toUpperCase(),
      question: question.trim() || null,
    });
  }

  const analyses = councilMut.data?.analyses || [];
  const consensus = computeConsensus(analyses);

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="card space-y-4">
        <SectionHeader title="Council 模式" subtitle="一次问 N 个 persona,看共识 / 分歧 — 上下文构建一次,LLM 调用 N 次" />

        {personasQ.isLoading ? (
          <LoadingState rows={2} />
        ) : (
          <div className="grid grid-cols-6 gap-2">
            {(personasQ.data?.items || []).map((p) => (
              <button
                type="button"
                key={p.id}
                onClick={() => togglePersona(p.id)}
                className={classNames(
                  'card-dense text-left card-hover relative',
                  selected.includes(p.id) ? 'border-steel-500 bg-ink-700' : ''
                )}
              >
                {selected.includes(p.id) && <Check size={12} className="absolute top-1.5 right-1.5 text-steel-500" />}
                <div className="text-caption text-accent-silver font-mono">{p.id}</div>
                <div className="text-body-sm font-medium text-steel-50 mt-0.5">{p.name.split(' ')[0]}</div>
              </button>
            ))}
          </div>
        )}

        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="h-caption block mb-2">Symbol</label>
            <input
              className="input uppercase"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            />
          </div>
          <div className="col-span-2">
            <label className="h-caption block mb-2">问题(可选)</label>
            <input
              className="input"
              placeholder="What's the long-term thesis here?"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
            />
          </div>
        </div>

        {councilMut.isError && <ApiErrorBanner error={councilMut.error} label="Council 失败" />}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            className="btn-primary"
            disabled={councilMut.isPending || selected.length === 0}
          >
            <Users size={14} /> {councilMut.isPending ? '运行中…' : `召集 ${selected.length} 位 persona`}
          </button>
          <span className="text-caption text-steel-300">
            将持久化 {selected.length} 条历史 · 估算约 {selected.length * 2000} tokens
          </span>
        </div>
      </form>

      {councilMut.isPending && (
        <div className="card"><LoadingState rows={6} label="所有 persona 思考中…" /></div>
      )}

      {analyses.length > 0 && (
        <>
          {consensus && (
            <div className="card">
              <SectionHeader title="共识 / 分歧" />
              <ConsensusBlock consensus={consensus} />
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            {analyses.map((a) => (
              <AnalysisResultCard key={a.id} analysis={a} compact />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function ConsensusBlock({ consensus }) {
  return (
    <div className="grid grid-cols-3 gap-4">
      <Tile label="Buy" value={consensus.buy} color="text-bull" />
      <Tile label="Hold" value={consensus.hold} color="text-steel-100" />
      <Tile label="Sell" value={consensus.sell} color="text-bear" />
    </div>
  );
}

function Tile({ label, value, color }) {
  return (
    <div className="card-dense text-center">
      <div className="metric-caption">{label}</div>
      <div className={classNames('text-display font-bold tabular mt-1', color)}>{value}</div>
    </div>
  );
}

function computeConsensus(analyses) {
  if (!analyses || analyses.length === 0) return null;
  const counts = { buy: 0, hold: 0, sell: 0 };
  for (const a of analyses) counts[a.verdict] = (counts[a.verdict] || 0) + 1;
  return counts;
}

// ---------------------------------------------------------- History

function HistoryTab() {
  const [symbolFilter, setSymbolFilter] = useState('');
  const historyQ = useQuery({
    queryKey: ['agent-history', symbolFilter],
    queryFn: () => listAgentHistory({ symbol: symbolFilter || undefined, limit: 100 }),
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-4">
      <div className="card">
        <SectionHeader title="历史分析" subtitle="所有 personas + 所有 symbols 的过往运行" />
        <div className="flex gap-3 items-end mb-4">
          <div className="max-w-xs flex-1">
            <label className="h-caption block mb-2">Symbol filter (留空显示全部)</label>
            <input
              className="input uppercase"
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value.toUpperCase())}
              placeholder="NVDA / 留空"
            />
          </div>
        </div>
        <HistoryList q={historyQ} />
      </div>
    </div>
  );
}

function HistoryList({ q }) {
  if (q.isLoading) return <LoadingState rows={5} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={q.refetch} />;
  const items = q.data?.items || [];
  if (items.length === 0) return <EmptyState icon={History} title="暂无历史" hint="先在 Personas / Council tab 跑一次。" />;

  return (
    <div className="space-y-3">
      {items.map((a) => (
        <details key={a.id} className="card-dense">
          <summary className="cursor-pointer flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <span className="font-mono text-caption text-accent-silver">{a.persona_id}</span>
              <span className="font-medium text-steel-50">{a.symbol}</span>
              <VerdictPill verdict={a.verdict} confidence={a.confidence} />
              <span className="text-body-sm text-steel-200 truncate">{a.reasoning_summary}</span>
            </div>
            <span className="text-caption text-steel-300 shrink-0">{fmtRelativeTime(a.created_at)}</span>
          </summary>
          <div className="mt-3 pl-3 border-l-2 border-steel-400">
            <AnalysisDetail a={a} />
          </div>
        </details>
      ))}
    </div>
  );
}

// ---------------------------------------------------------- Result card

function AnalysisResultCard({ analysis, compact = false }) {
  return (
    <div className="card">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-mono text-caption text-accent-silver mb-0.5">{analysis.persona_id}</div>
          <div className="h-section text-h2">{analysis.symbol}</div>
        </div>
        <VerdictPill verdict={analysis.verdict} confidence={analysis.confidence} />
      </div>
      <p className="text-body text-steel-100 leading-relaxed mb-4">{analysis.reasoning_summary}</p>
      <AnalysisDetail a={analysis} compact={compact} />
      <div className="text-caption text-steel-300 mt-3">
        {fmtRelativeTime(analysis.created_at)} · model {analysis.model || '—'}
      </div>
    </div>
  );
}

function AnalysisDetail({ a, compact = false }) {
  return (
    <div className="space-y-3">
      {a.key_factors?.length > 0 && (
        <div>
          <div className="h-caption mb-2">Key factors</div>
          <ul className="space-y-1.5">
            {a.key_factors.map((kf, i) => (
              <li key={i} className="flex items-start gap-2 text-body-sm">
                <span className={classNames(
                  'pill-default shrink-0 mt-0.5',
                  kf.signal === 'social' && 'pill-social',
                  kf.signal === 'fundamentals' && 'pill-active',
                  kf.signal === 'technical' && 'pill-warn',
                )}>{kf.signal}</span>
                <span className="text-steel-100">{kf.interpretation}</span>
                <span className="ml-auto text-caption text-steel-300 tabular shrink-0">w={(kf.weight || 0).toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!compact && a.follow_up_questions?.length > 0 && (
        <div>
          <div className="h-caption mb-2">Follow-up</div>
          <ul className="list-disc list-inside text-body-sm text-steel-100 space-y-1">
            {a.follow_up_questions.map((q, i) => <li key={i}>{q}</li>)}
          </ul>
        </div>
      )}

      {a.question && (
        <div className="text-caption text-steel-300 italic">提问: {a.question}</div>
      )}
    </div>
  );
}

function VerdictPill({ verdict, confidence }) {
  const cls = verdict === 'buy' ? 'pill-bull' : verdict === 'sell' ? 'pill-bear' : 'pill-default';
  return (
    <div className="text-right shrink-0">
      <span className={cls}>{verdict?.toUpperCase()}</span>
      <div className="text-caption text-steel-300 mt-1 tabular">conf {(confidence || 0).toFixed(2)}</div>
    </div>
  );
}
```

- [ ] **Step 3: Sidebar — drop the P7 badge**

In `frontend-v2/src/components/Sidebar.jsx`, remove the `badge: 'P7'` from the `/intelligence` nav item (it's now live).

- [ ] **Step 4: Build verify**

```bash
cd ~/NewBirdClaude/frontend-v2
npm run build
```
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend-v2/src/lib/api.js frontend-v2/src/pages/IntelligencePage.jsx frontend-v2/src/components/Sidebar.jsx
git commit -m "feat(frontend): wire IntelligencePage to AI Council backend (Personas / Council / History)"
```

---

## Task 10: Final verification + push

- [ ] **Step 1: Full backend sweep**

```bash
cd ~/NewBirdClaude/backend
source .venv/bin/activate
pytest tests/ -v
```
Expected: **151 passed**.

- [ ] **Step 2: Backend live boot**

```bash
(uvicorn app.main:app --port 8765 > /tmp/uv.log 2>&1 &); sleep 3
echo "--- agents/personas ---"
curl -s http://127.0.0.1:8765/api/agents/personas | head -c 400; echo
echo "--- agents/history ---"
curl -s http://127.0.0.1:8765/api/agents/history | head -c 200; echo
echo "--- existing endpoints ---"
for ep in /api/health /api/strategy/health /api/risk/policies /api/backtest/runs; do
  printf "%-32s -> " "$ep"
  curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765$ep"
done
pkill -f "uvicorn app.main:app --port 8765"; sleep 1
grep -E "ERROR|Exception" /tmp/uv.log | head -3
```
Expected:
- `/api/agents/personas` → JSON listing 6 personas including `sentinel`.
- `/api/agents/history` → `{"items": []}`.
- All other endpoints stay 200.

- [ ] **Step 3: Push**

```bash
git push -u origin feat/p7-ai-council
```

---

## Done-criteria

- All tasks committed on `feat/p7-ai-council`, branched from `feat/frontend-v2`.
- `pytest tests/` green: **151 passed**.
- New core/agents/ package with 6 modules and clear responsibilities.
- New table: `agent_analyses`.
- 4 new routes: `GET /api/agents/personas`, `POST /api/agents/analyze`, `POST /api/agents/council`, `GET /api/agents/history`.
- Frontend `IntelligencePage` shows real Personas / Council / History tabs.
- 6 personas wired:Buffett (value), Graham (strict value), Lynch (GARP),
  Soros (reflexivity / macro), Burry (contrarian), Sentinel (multi-signal
  synthesis with highest social-weight, our home-grown agent).
- LLM calls go through the OpenAI driver; service errors when no key are
  surfaced cleanly as 503 with actionable message.

After Phase 7 lands, **Phase 8 — QuantLib integration** plugs in option/Greeks/VaR/bond tooling, and **Phase 9 — Code editor** lets the user drop in their own `Strategy` subclasses.
