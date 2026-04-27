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
    assert PERSONA_INDEX["sentinel"].name.startswith("Newbird")
