"""Tests for the Factor Forge operator library, AST, and evaluator."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.factors.ast import (  # noqa: E402
    FactorNode,
    depth,
    node_count,
    parse,
    replace_subtree,
    serialize,
    walk,
)
from core.factors.eval import evaluate  # noqa: E402
from core.factors.ops import OPS, op_correlation, op_div, op_rank, op_ts_mean  # noqa: E402
from core.factors.seeds import SEEDS, get_seed_population  # noqa: E402


def _build_panel(n_days: int = 30, symbols=("AAA", "BBB", "CCC")) -> pd.DataFrame:
    """Build a deterministic OHLCV panel for testing."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    rows = []
    base_prices = {"AAA": 100.0, "BBB": 50.0, "CCC": 200.0}
    sectors = {"AAA": "tech", "BBB": "tech", "CCC": "energy"}
    mcaps = {"AAA": 1.0e9, "BBB": 5.0e8, "CCC": 2.0e9}
    for d in dates:
        for sym in symbols:
            drift = rng.normal(0, 0.01)
            price = base_prices[sym] * (1.0 + drift)
            base_prices[sym] = price
            high = price * 1.01
            low = price * 0.99
            open_ = price * (1.0 + rng.normal(0, 0.002))
            volume = float(rng.integers(100_000, 1_000_000))
            ret = drift
            vwap = (high + low + price) / 3.0
            rows.append(
                {
                    "date": d,
                    "symbol": sym,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": price,
                    "volume": volume,
                    "returns": ret,
                    "vwap": vwap,
                    "sector": sectors[sym],
                    "mcap": mcaps[sym],
                    "news_sent": rng.normal(0, 1.0),
                    "news_count": float(rng.integers(0, 10)),
                }
            )
    df = pd.DataFrame(rows).set_index(["date", "symbol"]).sort_index()
    return df


class FactorOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = _build_panel()
        self.symbols = ("AAA", "BBB", "CCC")
        self.n_days = 30

    # ------------------------------------------------------------------
    # operator unit tests
    # ------------------------------------------------------------------

    def test_rank_within_day(self) -> None:
        # Build a synthetic series with known ordering per day.
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        idx = pd.MultiIndex.from_product([dates, self.symbols], names=["date", "symbol"])
        # day 1: AAA=10, BBB=20, CCC=30  (ranks 1/3, 2/3, 3/3)
        # day 2: AAA=30, BBB=20, CCC=10
        values = [10.0, 20.0, 30.0, 30.0, 20.0, 10.0]
        s = pd.Series(values, index=idx)
        ranked = op_rank(s)
        self.assertAlmostEqual(ranked.loc[(dates[0], "AAA")], 1 / 3)
        self.assertAlmostEqual(ranked.loc[(dates[0], "CCC")], 1.0)
        self.assertAlmostEqual(ranked.loc[(dates[1], "AAA")], 1.0)
        self.assertAlmostEqual(ranked.loc[(dates[1], "CCC")], 1 / 3)

    def test_ts_mean(self) -> None:
        result = op_ts_mean(self.panel["close"], 5)
        # rolling 5-day mean for symbol AAA at the 5th bar should equal mean of first 5
        first_aaa = self.panel["close"].xs("AAA", level="symbol").iloc[:5].mean()
        date_5 = self.panel.index.get_level_values("date").unique()[4]
        self.assertAlmostEqual(result.loc[(date_5, "AAA")], first_aaa, places=8)
        # warmup cells should be NaN
        date_1 = self.panel.index.get_level_values("date").unique()[0]
        self.assertTrue(np.isnan(result.loc[(date_1, "AAA")]))

    def test_correlation_rolling(self) -> None:
        # x perfectly correlates with itself  expect 1.0 after warmup
        x = self.panel["close"]
        corr = op_correlation(x, x, 5)
        date_10 = self.panel.index.get_level_values("date").unique()[9]
        self.assertAlmostEqual(corr.loc[(date_10, "AAA")], 1.0, places=8)

    def test_safe_div_handles_zero(self) -> None:
        x = self.panel["close"]
        zero = pd.Series(0.0, index=x.index)
        result = op_div(x, zero)
        # divide by zero  every cell should be 0
        self.assertTrue((result == 0).all())

    def test_delta_and_delay(self) -> None:
        delta = OPS["delta"](self.panel["close"], 1)
        delay = OPS["delay"](self.panel["close"], 1)
        date_2 = self.panel.index.get_level_values("date").unique()[1]
        date_1 = self.panel.index.get_level_values("date").unique()[0]
        expected = (
            self.panel["close"].loc[(date_2, "AAA")]
            - self.panel["close"].loc[(date_1, "AAA")]
        )
        self.assertAlmostEqual(delta.loc[(date_2, "AAA")], expected, places=10)
        self.assertAlmostEqual(
            delay.loc[(date_2, "AAA")],
            self.panel["close"].loc[(date_1, "AAA")],
            places=10,
        )

    def test_zscore_per_day(self) -> None:
        zs = OPS["zscore"](self.panel["close"])
        # within a day, mean of zscored values should be ~0
        per_day_mean = zs.groupby(level="date").mean()
        for v in per_day_mean.dropna():
            self.assertAlmostEqual(v, 0.0, places=8)

    def test_signed_log_and_power(self) -> None:
        x = pd.Series(
            [-2.0, 0.0, 2.0],
            index=pd.MultiIndex.from_tuples(
                [("d", "a"), ("d", "b"), ("d", "c")], names=["date", "symbol"]
            ),
        )
        log_x = OPS["log"](x)
        # sign preserved
        self.assertLess(log_x.iloc[0], 0)
        self.assertGreater(log_x.iloc[2], 0)
        pow_x = OPS["power"](x, 2)
        self.assertEqual(pow_x.iloc[0], -4.0)
        self.assertEqual(pow_x.iloc[2], 4.0)

    # ------------------------------------------------------------------
    # AST tests
    # ------------------------------------------------------------------

    def test_serialize_roundtrip(self) -> None:
        node = parse("rank(delta(close,5))")
        self.assertEqual(serialize(node), "rank(delta(close,5))")

    def test_unknown_column_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse("rank(unknown_column)")

    def test_depth_and_node_count(self) -> None:
        node = parse("rank(delta(close,5))")
        self.assertEqual(depth(node), 2)
        self.assertEqual(node_count(node), 2)

    def test_walk_yields_children(self) -> None:
        node = parse("rank(delta(close,5))")
        children = [c for _, _, c in walk(node)]
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].op, "delta")

    def test_replace_subtree(self) -> None:
        node = parse("rank(delta(close,5))")
        replacement = parse("ts_mean(close,10)")
        new_node = replace_subtree(node, (0,), replacement)
        self.assertEqual(serialize(new_node), "rank(ts_mean(close,10))")

    def test_parse_negative_number(self) -> None:
        node = parse("power(close,-2)")
        self.assertEqual(node.args[1], -2)

    # ------------------------------------------------------------------
    # evaluator + seeds
    # ------------------------------------------------------------------

    def test_eval_simple_factor(self) -> None:
        node = parse("rank(close)")
        result = evaluate(node, self.panel)
        self.assertIsInstance(result, pd.Series)
        self.assertEqual(result.shape[0], self.n_days * len(self.symbols))
        self.assertTrue(result.dropna().between(0, 1).all())

    def test_eval_alpha_seed(self) -> None:
        # Alpha #41: sqrt(high*low) - vwap  produces fully finite output on
        # this panel because it has no rolling reductions or rank ties.
        node = parse(SEEDS[19])
        result = evaluate(node, self.panel)
        self.assertEqual(result.shape, (self.n_days * len(self.symbols),))
        self.assertTrue(np.isfinite(result).all())

    def test_eval_seeds_smoke(self) -> None:
        # Every seed must parse + evaluate without raising; output shape
        # matches the panel index.
        for raw in SEEDS:
            node = parse(raw)
            out = evaluate(node, self.panel)
            self.assertEqual(out.shape[0], self.n_days * len(self.symbols))

    def test_eval_handles_errors_with_nan(self) -> None:
        # Build a node referencing a column the panel does not have  evaluator
        # should bail out into NaN rather than raising.
        panel = self.panel.drop(columns=["news_sent"])
        node = parse("rank(news_sent)")
        result = evaluate(node, panel)
        self.assertTrue(result.isna().all())

    def test_seed_population_parses(self) -> None:
        pop = get_seed_population()
        self.assertGreaterEqual(len(pop), 10)
        for n in pop:
            self.assertIsInstance(n, FactorNode)

    def test_op_count_meets_target(self) -> None:
        self.assertGreaterEqual(len(OPS), 30)


if __name__ == "__main__":
    unittest.main()
