"""DataHub bus + topic + matching unit tests.

Pure-compute layer — no FastAPI, no asyncio.create_task at module import,
no DB. Each test constructs a fresh Bus to avoid singleton pollution.
"""
from __future__ import annotations

import asyncio
import dataclasses
import pytest

from core.datahub import Topic
from core.datahub.matching import pattern_matches, is_glob_pattern


# ---------- Topic ----------------------------------------------------------


def test_topic_has_sane_defaults() -> None:
    # Arrange / Act
    topic = Topic(name="market:quote:SPY")

    # Assert
    assert topic.name == "market:quote:SPY"
    assert topic.ttl_seconds is None
    assert topic.throttle_seconds == 0.0
    assert topic.replay_on_subscribe is False
    assert topic.dedupe_key_fn is None


def test_topic_is_frozen() -> None:
    topic = Topic(name="market:quote:SPY")
    with pytest.raises(dataclasses.FrozenInstanceError):
        topic.ttl_seconds = 60  # type: ignore[misc]


# ---------- matching -------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,topic,expected",
    [
        # Exact match (no glob characters)
        ("market:quote:SPY", "market:quote:SPY", True),
        ("market:quote:SPY", "market:quote:AAPL", False),

        # Single-segment wildcard
        ("market:quote:*", "market:quote:SPY", True),
        ("market:quote:*", "market:quote:AAPL", True),
        ("market:quote:*", "market:trade:SPY", False),

        # Multi-segment wildcard via `*` (fnmatch treats * greedy across `:`)
        ("market:*", "market:quote:SPY", True),
        ("market:*", "market:trade:SPY", True),
        ("market:*", "broker:ibkr:positions", False),

        # `?` single char
        ("market:quote:SP?", "market:quote:SPY", True),
        ("market:quote:SP?", "market:quote:SPYY", False),

        # Empty / pathological
        ("", "", True),
        ("market:quote:SPY", "", False),
    ],
)
def test_pattern_matches(pattern: str, topic: str, expected: bool) -> None:
    assert pattern_matches(pattern, topic) is expected


@pytest.mark.parametrize(
    "candidate,expected",
    [
        ("market:quote:*", True),
        ("market:quote:SP?", True),
        ("market:quote:[ABC]", True),
        ("market:quote:SPY", False),
        ("", False),
    ],
)
def test_is_glob_pattern(candidate: str, expected: bool) -> None:
    assert is_glob_pattern(candidate) is expected
