"""Tests for operator-success weight computation."""
from __future__ import annotations

import random
import unittest


class OpStatsTests(unittest.TestCase):
    def test_ops_in_formula_extracts_op_tokens(self) -> None:
        from core.factors.op_stats import _ops_in_formula
        self.assertEqual(_ops_in_formula("rank(close)"), {"rank"})
        self.assertEqual(_ops_in_formula("rank(delta(close,5))"), {"rank", "delta"})
        self.assertEqual(_ops_in_formula(""), set())

    def test_compute_op_weights_biases_toward_high_fitness_ops(self) -> None:
        from core.factors.op_stats import compute_op_weights
        records = [
            {"formula": "rank(close)", "fitness": 0.10},
            {"formula": "rank(volume)", "fitness": 0.08},
            {"formula": "ts_max(close,20)", "fitness": 0.01},
        ]
        w = compute_op_weights(records)
        self.assertGreater(w["rank"], w["ts_max"])

    def test_compute_op_weights_floors_negatives(self) -> None:
        from core.factors.op_stats import compute_op_weights
        records = [{"formula": "rank(close)", "fitness": -1.0}]
        w = compute_op_weights(records)
        self.assertGreater(w["rank"], 0)  # epsilon floor

    def test_compute_op_weights_falls_back_to_ic_5d(self) -> None:
        from core.factors.op_stats import compute_op_weights
        records = [
            {"formula": "rank(close)", "ic_5d": 0.05},
            {"formula": "ts_max(close,20)", "ic_5d": 0.01},
        ]
        w = compute_op_weights(records)
        self.assertGreater(w["rank"], w["ts_max"])

    def test_weighted_op_choice_with_uniform_falls_back_to_choice(self) -> None:
        from core.factors.op_stats import weighted_op_choice
        rng = random.Random(0)
        op = weighted_op_choice(["a", "b", "c"], None, rng)
        self.assertIn(op, {"a", "b", "c"})

    def test_weighted_op_choice_biases_toward_heavy_weight(self) -> None:
        from core.factors.op_stats import weighted_op_choice
        rng = random.Random(0)
        weights = {"hot": 100.0, "cold": 0.001}
        picks = [weighted_op_choice(["hot", "cold"], weights, rng) for _ in range(200)]
        self.assertGreater(picks.count("hot"), 180)

    def test_weighted_op_choice_empty_raises(self) -> None:
        from core.factors.op_stats import weighted_op_choice
        rng = random.Random(0)
        with self.assertRaises(ValueError):
            weighted_op_choice([], {"a": 1.0}, rng)


if __name__ == "__main__":
    unittest.main()
