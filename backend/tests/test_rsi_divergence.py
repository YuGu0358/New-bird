from __future__ import annotations
import unittest
from core.signals.rsi_divergence import detect_rsi_divergences


class RSIDivergenceTests(unittest.TestCase):
    def test_bullish_divergence_emits_buy_signal(self) -> None:
        # Construct a sequence with two prominent price lows where the second
        # low is slightly deeper than the first, but built so RSI's second
        # trough is HIGHER than the first (weaker selling momentum / HL on RSI).
        # Sequence: warmup -> steep leg 1 -> strong rebound -> jittery leg 2
        # (deeper price low but RSI stays elevated thanks to frequent up-bars)
        # -> final bounce.
        prices: list[float] = []
        v = 100.0
        for i in range(25):  # warmup oscillation
            v += 0.5 if i % 2 == 0 else -0.5
            prices.append(v)
        for _ in range(12):  # steep leg 1
            v -= 1.5
            prices.append(v)
        for _ in range(3):   # crisp pivot at leg-1 low
            v += 0.5; prices.append(v)
            v -= 1.5; prices.append(v)
        for _ in range(25):  # strong rebound
            v += 1.5
            prices.append(v)
        for i in range(35):  # leg 2: deeper but with frequent rebounds
            v -= 1.5
            if i % 3 == 2:
                v += 1.6
            prices.append(v)
        for _ in range(3):   # crisp pivot at leg-2 low
            v += 0.6; prices.append(v)
            v -= 1.5; prices.append(v)
        for _ in range(15):  # final bounce
            v += 0.5
            prices.append(v)

        signals = detect_rsi_divergences(prices, period=14, pivot_window=5, min_separation=10)
        kinds = [s.kind for s in signals]
        self.assertIn("rsi_bullish_divergence", kinds)
        bull = next(s for s in signals if s.kind == "rsi_bullish_divergence")
        self.assertEqual(bull.direction, "buy")
        self.assertGreater(bull.strength, 0.0)

    def test_no_divergence_on_short_history(self) -> None:
        prices = [100.0 + i * 0.1 for i in range(10)]
        self.assertEqual(detect_rsi_divergences(prices, period=14), [])

    def test_no_divergence_on_pure_uptrend(self) -> None:
        prices = [100.0 + i * 0.5 for i in range(80)]
        signals = detect_rsi_divergences(prices, period=14, pivot_window=5, min_separation=10)
        # Pure uptrend should not produce a bullish divergence (no LL).
        self.assertNotIn("rsi_bullish_divergence", [s.kind for s in signals])


if __name__ == "__main__":
    unittest.main()
