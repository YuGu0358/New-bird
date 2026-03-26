from __future__ import annotations

import unittest

from app.services import strategy_document_service


class StrategyDocumentServiceTests(unittest.TestCase):
    def test_extract_strategy_documents_reads_markdown(self) -> None:
        documents = strategy_document_service.extract_strategy_documents(
            [
                (
                    "strategy-note.md",
                    "# 回撤策略\n\n关注 NVDA 和 MSFT，日内回撤 3% 时分批买入。".encode("utf-8"),
                )
            ]
        )

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["name"], "strategy-note.md")
        self.assertIn("NVDA", documents[0]["content"])

    def test_extract_strategy_documents_rejects_unsupported_file_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "仅支持上传 PDF、Markdown 或 TXT"):
            strategy_document_service.extract_strategy_documents([("notes.docx", b"abc")])


if __name__ == "__main__":
    unittest.main()
