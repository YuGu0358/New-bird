"""Glob-style topic matching.

Why fnmatch and not regex: our taxonomy uses colon-segment names
(`market:quote:SPY`) and the only wildcard semantics we need are `*`
(any chars including colon — matches "everything below this level"),
`?` (any single char), and `[seq]`. fnmatch from stdlib gives us all
three with predictable behaviour and no engine-flavour drift.

Subtlety: in our taxonomy, `market:quote:*` is intuitively expected to
match `market:quote:SPY` but NOT `market:quote:SPY:extra`. Today we
DO NOT enforce that — `*` is greedy across `:`. If the future taxonomy
grows a fourth segment we revisit; the current registered topics are
all 2- or 3-segment, so this is fine.
"""
from __future__ import annotations

import fnmatch


_GLOB_CHARS = ("*", "?", "[")


def pattern_matches(pattern: str, topic: str) -> bool:
    """Return True iff `topic` matches the glob `pattern`.

    Exact-string equality short-circuits before fnmatch so callers that
    pass non-glob topic names pay no regex-compile cost.
    """
    if not any(c in pattern for c in _GLOB_CHARS):
        return pattern == topic
    return fnmatch.fnmatchcase(topic, pattern)


def is_glob_pattern(candidate: str) -> bool:
    """True iff `candidate` contains a glob metacharacter.

    Used by the SSE router to decide whether to subscribe to one topic
    or to a wildcard pattern.
    """
    return any(c in candidate for c in _GLOB_CHARS)
