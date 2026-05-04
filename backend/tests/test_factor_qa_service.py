from __future__ import annotations
import unittest
from unittest.mock import MagicMock, patch

from tests._factor_test_isolation import (
    factor_test_isolation_setup,
    factor_test_isolation_teardown,
)


class _FakeFunctionCall:
    def __init__(self, name, args, call_id="c1"):
        self.type = "function_call"
        self.name = name
        self.arguments = args
        self.call_id = call_id


class _FakeMessageContent:
    def __init__(self, text):
        self.type = "output_text"
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.type = "message"
        self.content = [_FakeMessageContent(text)]


class _FakeResponse:
    def __init__(self, output):
        self.output = output


class FactorQAServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._iso = await factor_test_isolation_setup(
            services=["factor_qa_service"]
        )

    async def asyncTearDown(self):
        await factor_test_isolation_teardown(self._iso)

    async def test_safety_check_rejects_destructive_keywords(self):
        from app.services import factor_qa_service as svc
        result = await svc.answer_question("rm -rf 我的电脑")
        self.assertTrue(result["blocked"])
        self.assertIn("rm -rf", result["answer"])

    async def test_safety_check_allows_legitimate_questions_about_subprocess(self):
        from app.services import factor_qa_service as svc
        fake_client = MagicMock()
        fake_client.responses.create.return_value = _FakeResponse(
            [_FakeMessage("subprocess 启动慢可能是因为...")]
        )
        with patch.object(svc, "create_client", return_value=fake_client):
            result = await svc.answer_question("subprocess 启动太慢了为什么")
        self.assertFalse(result["blocked"])

    async def test_safety_check_rejects_long_questions(self):
        from app.services import factor_qa_service as svc
        result = await svc.answer_question("a" * 600)
        self.assertTrue(result["blocked"])

    async def test_one_round_no_tools(self):
        from app.services import factor_qa_service as svc

        fake_client = MagicMock()
        fake_client.responses.create.return_value = _FakeResponse([_FakeMessage("库里目前 0 个因子")])
        with patch.object(svc, "create_client", return_value=fake_client):
            result = await svc.answer_question("库里有多少因子")
        self.assertEqual(result["answer"], "库里目前 0 个因子")
        self.assertFalse(result["blocked"])

    async def test_tool_loop_executes_tool_then_answers(self):
        """LLM round 1: ask for top factors. Round 2: produce final answer."""
        from app.services import factor_qa_service as svc

        round_1 = _FakeResponse([_FakeFunctionCall("get_top_factors", '{"n": 3}', "c1")])
        round_2 = _FakeResponse([_FakeMessage("库里前 3 个因子是 X、Y、Z")])
        fake_client = MagicMock()
        fake_client.responses.create.side_effect = [round_1, round_2]
        with patch.object(svc, "create_client", return_value=fake_client):
            result = await svc.answer_question("库里前 3 因子是哪些")
        self.assertIn("库里前", result["answer"])
        self.assertEqual(len(result["tool_calls"]), 1)
        self.assertEqual(result["tool_calls"][0]["name"], "get_top_factors")

    async def test_unknown_tool_returns_error_payload(self):
        from app.services import factor_qa_service as svc

        round_1 = _FakeResponse([_FakeFunctionCall("nonexistent_tool", "{}", "c1")])
        round_2 = _FakeResponse([_FakeMessage("无法回答")])
        fake_client = MagicMock()
        fake_client.responses.create.side_effect = [round_1, round_2]
        with patch.object(svc, "create_client", return_value=fake_client):
            result = await svc.answer_question("哎")
        self.assertIn("unknown tool", result["tool_calls"][0]["result_preview"])

    async def test_no_openai_key_returns_blocked(self):
        from app.services import factor_qa_service as svc
        with patch.object(svc, "create_client", side_effect=RuntimeError("OPENAI_API_KEY missing")):
            result = await svc.answer_question("test")
        self.assertTrue(result["blocked"])
        self.assertIn("OpenAI", result["answer"])


if __name__ == "__main__":
    unittest.main()
