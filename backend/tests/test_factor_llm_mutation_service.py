import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class _FakeVariant:
    def __init__(self, formula, rationale):
        self.formula = formula
        self.rationale = rationale


class _FakeResult:
    def __init__(self, variants):
        self.variants = variants


class _FakeResponse:
    def __init__(self, parsed):
        self.output_parsed = parsed


class FactorLLMMutationTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_variants_parses_valid_formulas(self):
        from app.services import factor_llm_mutation_service as svc
        fake_result = _FakeResult([
            _FakeVariant("rank(close)", "Simple rank"),
            _FakeVariant("ts_mean(volume,20)", "20-day volume MA"),
            _FakeVariant("not-a-formula!!!", "Bad"),
        ])
        with patch.object(svc, "_generate_sync", return_value=fake_result):
            variants = await svc.generate_variants([{"formula": "rank(close)", "ic_5d": 0.05}], n_variants=3)
        self.assertEqual(len(variants), 2)
        self.assertEqual(svc.serialize(variants[0]), "rank(close)")

    async def test_generate_variants_returns_empty_when_no_top_factors(self):
        from app.services import factor_llm_mutation_service as svc
        result = await svc.generate_variants([], n_variants=5)
        self.assertEqual(result, [])

    async def test_generate_variants_swallows_openai_errors(self):
        from app.services import factor_llm_mutation_service as svc
        with patch.object(svc, "_generate_sync", side_effect=RuntimeError("no api key")):
            result = await svc.generate_variants([{"formula": "rank(close)", "ic_5d": 0.05}])
        self.assertEqual(result, [])

    async def test_generate_variants_strips_quote_wrappers(self):
        from app.services import factor_llm_mutation_service as svc
        fake_result = _FakeResult([
            _FakeVariant("`rank(volume)`", "quoted"),
            _FakeVariant('"zscore(close)"', "double-quoted"),
        ])
        with patch.object(svc, "_generate_sync", return_value=fake_result):
            variants = await svc.generate_variants([{"formula": "x", "ic_5d": 0.1}])
        self.assertEqual(len(variants), 2)

    async def test_prompt_contains_operator_list_and_columns(self):
        from app.services.factor_llm_mutation_service import _build_prompt
        prompt = _build_prompt([{"formula": "rank(close)", "ic_5d": 0.07}], 5)
        self.assertIn("rank", prompt)
        self.assertIn("close", prompt)
        self.assertIn("0.0700", prompt)
        self.assertIn("Available operators:", prompt)
