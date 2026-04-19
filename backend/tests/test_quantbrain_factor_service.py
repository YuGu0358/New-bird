from __future__ import annotations

import unittest

from app.services import quantbrain_factor_service


class QuantBrainFactorServiceTests(unittest.TestCase):
    def test_static_analysis_extracts_factor_shape(self) -> None:
        code = """
factor_name = "momentum_breakout"

def alpha(df):
    momentum = df["close"] / df["close"].shift(20) - 1
    volume_filter = df["volume"].rolling(10).mean()
    buy_signal = momentum > 0.08
    sell_signal = momentum < -0.03
    return momentum.rank(ascending=False)
"""

        analysis = quantbrain_factor_service.analyze_factor_code(code, source_name="alpha.py")

        self.assertEqual(analysis.source_name, "alpha.py")
        self.assertIn("momentum_breakout", analysis.factor_names)
        self.assertIn("close", analysis.input_fields)
        self.assertIn("volume", analysis.input_fields)
        self.assertIn(20, analysis.windows)
        self.assertIn(10, analysis.windows)
        self.assertEqual(analysis.sort_direction, "higher_is_better")
        self.assertTrue(any("momentum > 0.08" in item for item in analysis.buy_conditions))
        self.assertTrue(any("momentum < -0.03" in item for item in analysis.sell_conditions))
        self.assertTrue(analysis.safe_static_analysis)

    def test_static_analysis_flags_dangerous_code_without_executing(self) -> None:
        code = """
import os

def factor(df):
    payload = eval("1 + 1")
    future_return = df["close"].shift(-1)
    return future_return
"""

        analysis = quantbrain_factor_service.analyze_factor_code(code)

        self.assertTrue(any("import os" in item for item in analysis.unsupported_features))
        self.assertTrue(any("eval" in item for item in analysis.unsupported_features))
        self.assertTrue(any("未来" in item or "前视" in item for item in analysis.risk_flags))

    def test_upload_decoder_accepts_factor_code_files(self) -> None:
        documents = quantbrain_factor_service.extract_factor_code_files(
            [("factor.md", b"def alpha(df):\n    return df['close'].rolling(5).mean()\n")]
        )

        self.assertEqual(documents[0]["name"], "factor.md")
        self.assertIn("rolling", documents[0]["code"])

    def test_upload_decoder_rejects_unsupported_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "仅支持"):
            quantbrain_factor_service.extract_factor_code_files([("factor.pdf", b"not code")])


if __name__ == "__main__":
    unittest.main()
