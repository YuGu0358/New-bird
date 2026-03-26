from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader

_ALLOWED_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt"}
_MAX_ATTACHMENTS = 5
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_TEXT_CHARS = 12_000


def _decode_text_bytes(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文本附件当前无法解码，请改用 UTF-8 或 Markdown 文本。")


def _extract_pdf_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload))
    sections: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            sections.append(text)
    return "\n\n".join(sections).strip()


def extract_strategy_documents(files: list[tuple[str, bytes]]) -> list[dict[str, Any]]:
    """Parse uploaded PDF/Markdown/TXT files into compact text snippets for strategy analysis."""

    if len(files) > _MAX_ATTACHMENTS:
        raise ValueError(f"一次最多只能上传 {_MAX_ATTACHMENTS} 个附件。")

    documents: list[dict[str, Any]] = []
    for file_name, payload in files:
        normalized_name = Path(str(file_name or "strategy-note.txt")).name
        suffix = Path(normalized_name).suffix.lower()
        if suffix not in _ALLOWED_EXTENSIONS:
            raise ValueError("目前仅支持上传 PDF、Markdown 或 TXT 文档。")
        if len(payload) > _MAX_FILE_BYTES:
            raise ValueError(f"{normalized_name} 超过 5MB，请压缩后再上传。")

        if suffix == ".pdf":
            text = _extract_pdf_text(payload)
        else:
            text = _decode_text_bytes(payload)

        normalized_text = " ".join(str(text).split()).strip()
        if not normalized_text:
            raise ValueError(f"{normalized_name} 当前没有可提取的文字内容。")

        documents.append(
            {
                "name": normalized_name,
                "content": normalized_text[:_MAX_TEXT_CHARS],
            }
        )

    return documents
