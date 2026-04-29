"""Docs panel service — serve markdown from the repo's docs/ tree.

Resolves the docs root from the DOCS_ROOT_DIR setting, falling back to
`<repo_root>/docs`. The path-traversal guard runs in two layers: the slug
allowlist in core.docs.scanner.slug_to_path rejects suspicious slugs
upfront, and we re-validate via Path.resolve(strict=True) + commonpath
so any symlink or unusual filesystem trickery still can't escape.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import runtime_settings
from core.docs import (
    DocEntry,
    extract_title,
    scan_docs_root,
    slug_to_path,
)

logger = logging.getLogger(__name__)


def _docs_root() -> Path:
    override = (runtime_settings.get_setting("DOCS_ROOT_DIR", "") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    # backend/app/services/docs_service.py → repo root is parents[3].
    return (Path(__file__).resolve().parents[3] / "docs").resolve()


def _serialize(entry: DocEntry) -> dict[str, Any]:
    return {
        "slug": entry.slug,
        "title": entry.title,
        "path": entry.path,
        "size_bytes": entry.size_bytes,
        "modified_at": entry.modified_at,
    }


async def list_docs() -> dict[str, Any]:
    """Return a flat catalogue of every markdown doc under the docs root."""
    root = _docs_root()
    items = scan_docs_root(root)
    return {
        "items": [_serialize(e) for e in items],
        "total": len(items),
        "root": str(root),
        "as_of": datetime.now(timezone.utc),
    }


async def get_doc(slug: str) -> dict[str, Any]:
    """Return the raw markdown content for a single doc.

    Raises:
        LookupError: when the slug is unknown / file missing → 404.
        PermissionError: when path resolution escapes the docs root → 400.
    """
    rel = slug_to_path(slug)
    if rel is None:
        raise PermissionError(f"Invalid doc slug: {slug!r}")

    # Resolve both ends so the commonpath check is robust against macOS
    # /var → /private/var symlink and similar fs aliasing.
    root = _docs_root().resolve()
    candidate = (root / rel).resolve()
    try:
        common = os.path.commonpath([str(root), str(candidate)])
    except ValueError:
        # Different drives on Windows.
        raise PermissionError(f"Invalid doc slug: {slug!r}") from None
    if common != str(root):
        raise PermissionError(f"Invalid doc slug: {slug!r}")

    if not candidate.exists() or not candidate.is_file():
        raise LookupError(f"Doc not found: {slug}")

    try:
        content = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LookupError(f"Doc not readable: {slug}") from exc

    stat = candidate.stat()
    title = extract_title(content, fallback=candidate.stem)
    return {
        "slug": slug,
        "title": title,
        "path": candidate.relative_to(root).as_posix(),
        "content": content,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        "as_of": datetime.now(timezone.utc),
    }
