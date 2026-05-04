"""Pure unit tests for genetic operators on factor ASTs.

These tests never touch the DB or the backtest engine — they exercise
``core.factors.genetic`` against the AST primitives only.
"""
from __future__ import annotations

import random

import pytest

from core.factors import FactorNode, parse, depth as ast_depth, serialize
from core.factors.genetic import (
    crossover,
    mutate,
    random_leaf,
    random_tree,
    tournament_select,
)


# ---------------------------------------------------------------------------
# random_tree
# ---------------------------------------------------------------------------


def test_random_tree_returns_factornode():
    rng = random.Random(0)
    tree = random_tree(rng, max_depth=3)
    assert isinstance(tree, FactorNode)


def test_random_tree_respects_max_depth():
    rng = random.Random(1)
    for _ in range(20):
        tree = random_tree(rng, max_depth=3)
        assert ast_depth(tree) <= 3


def test_random_tree_serialises_and_reparses():
    """A random tree must round-trip via serialize/parse."""
    rng = random.Random(42)
    for _ in range(10):
        tree = random_tree(rng, max_depth=3)
        text = serialize(tree)
        reparsed = parse(text)
        assert serialize(reparsed) == text


def test_random_leaf_returns_known_token_or_number():
    rng = random.Random(7)
    seen_types: set[type] = set()
    for _ in range(50):
        leaf = random_leaf(rng)
        seen_types.add(type(leaf))
        assert isinstance(leaf, (str, int, float))
    # over 50 draws we expect to see at least two of {str, int, float}
    assert len(seen_types) >= 2


# ---------------------------------------------------------------------------
# crossover
# ---------------------------------------------------------------------------


def test_crossover_returns_factornode():
    rng = random.Random(2)
    a = random_tree(rng, max_depth=3)
    b = random_tree(rng, max_depth=3)
    child = crossover(a, b, rng)
    assert isinstance(child, FactorNode)


def test_crossover_does_not_mutate_parents():
    rng = random.Random(3)
    a = random_tree(rng, max_depth=3)
    b = random_tree(rng, max_depth=3)
    a_serial_before = serialize(a)
    b_serial_before = serialize(b)
    crossover(a, b, rng)
    assert serialize(a) == a_serial_before
    assert serialize(b) == b_serial_before


def test_crossover_child_serialises():
    rng = random.Random(4)
    for _ in range(10):
        a = random_tree(rng, max_depth=3)
        b = random_tree(rng, max_depth=3)
        child = crossover(a, b, rng)
        # Should produce a structurally valid serialisation.
        text = serialize(child)
        assert text and "(" in text


# ---------------------------------------------------------------------------
# mutate
# ---------------------------------------------------------------------------


def test_mutate_with_zero_rate_is_noop():
    rng = random.Random(5)
    tree = random_tree(rng, max_depth=3)
    mutated = mutate(tree, rng, mutation_rate=0.0)
    assert serialize(mutated) == serialize(tree)


def test_mutate_with_full_rate_changes_tree():
    """With mutation_rate=1.0 across many trials, the result should differ
    from the input most of the time."""
    rng = random.Random(6)
    differences = 0
    trials = 30
    for _ in range(trials):
        tree = random_tree(rng, max_depth=3)
        mutated = mutate(tree, rng, mutation_rate=1.0)
        if serialize(mutated) != serialize(tree):
            differences += 1
    # Allow a few no-ops (e.g. arity-1 op-swap with no peers + replacement
    # collision), but the vast majority must differ.
    assert differences >= trials * 0.7


def test_mutate_does_not_mutate_input():
    rng = random.Random(7)
    tree = parse("rank(delta(close,5))")
    before = serialize(tree)
    mutate(tree, rng, mutation_rate=1.0)
    assert serialize(tree) == before


# ---------------------------------------------------------------------------
# tournament_select
# ---------------------------------------------------------------------------


def test_tournament_select_returns_fittest():
    rng = random.Random(8)
    pop = [parse("rank(close)"), parse("rank(open)"), parse("rank(volume)")]
    fits = [0.1, 0.5, 0.3]
    # k = full population — must return the index-1 (highest fitness)
    winner = tournament_select(pop, fits, k=3, rng=rng)
    assert serialize(winner) == "rank(open)"


def test_tournament_select_empty_raises():
    rng = random.Random(9)
    with pytest.raises(ValueError):
        tournament_select([], [], k=2, rng=rng)


def test_tournament_select_mismatched_lengths_raises():
    rng = random.Random(10)
    pop = [parse("rank(close)")]
    with pytest.raises(ValueError):
        tournament_select(pop, [0.1, 0.2], k=1, rng=rng)


# ---------------------------------------------------------------------------
# Determinism: same RNG seed produces identical streams.
# ---------------------------------------------------------------------------


def test_random_tree_is_deterministic_given_seed():
    a = serialize(random_tree(random.Random(123), max_depth=3))
    b = serialize(random_tree(random.Random(123), max_depth=3))
    assert a == b


# ---------------------------------------------------------------------------
# Weighted mutation
# ---------------------------------------------------------------------------


def test_mutate_with_op_weights_biases_swap():
    """When mutation does an op-swap, weights should bias the choice."""
    base = parse("rank(close)")
    weights = {"zscore": 100.0}  # heavy bias to zscore; others fall back to epsilon
    rng = random.Random(0)
    swap_outcomes = []
    for _ in range(50):
        # Force mutation_rate=1.0 so every mutate definitely changes something.
        rng2 = random.Random(rng.randrange(10_000))
        mutated = mutate(base, rng2, mutation_rate=1.0, op_weights=weights)
        swap_outcomes.append(serialize(mutated))
    zscore_count = sum(1 for s in swap_outcomes if "zscore" in s)
    # Mutation has two branches (subtree replace OR op swap); each ~50% likely.
    # Of the op-swap halves, with weights={"zscore":100} most should be zscore.
    # Conservative: at least 5 of 50 outcomes contain "zscore".
    assert zscore_count > 5
