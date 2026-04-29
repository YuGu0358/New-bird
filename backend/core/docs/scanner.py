"""Markdown scanner — directory walk + title extraction.

Pure compute. Takes a docs root path and returns a flat list of `DocEntry`
records sorted by relative path. Title extraction priority:
1. YAML front-matter `title:` field (if present between `---` fences).
2. First-level markdown heading (`# Title`).
3. Fallback to the filename without extension.

The slug encoding uses double-underscore for path separators so URLs stay
opaque (`docs/superpowers/plans/foo.md` → `superpowers__plans__foo`).
Round-trip via `slug_to_path` validates the slug only contains the allowed
charset before reconstructing — defense-in-depth on top of the service-layer
path-traversal guard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_SLUG_SEP = "__"
_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_\-./]+$")
_FRONT_MATTER_TITLE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)
_H1_LINE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class DocEntry:
    slug: str
    title: str
    path: str  # relative-to-docs-root posix path, for display
    size_bytes: int
    modified_at: datetime


def path_to_slug(rel_path: str) -> str:
    """Encode a relative posix path into a URL-safe slug.

    `superpowers/plans/foo.md` → `superpowers__plans__foo`
    The `.md` extension is stripped — every doc is markdown by construction.
    """
    p = rel_path.replace("\\", "/").lstrip("./")
    if p.endswith(".md"):
        p = p[:-3]
    return p.replace("/", _SLUG_SEP)


def slug_to_path(slug: str) -> str | None:
    """Decode a slug back to a relative path. Returns None for invalid slugs.

    Strict allowlist (no `..`, no leading slash) prevents path-traversal
    attempts before the service layer's resolved-path check ever runs.
    """
    if not slug or ".." in slug or slug.startswith("/"):
        return None
    if not _SLUG_PATTERN.match(slug):
        return None
    return slug.replace(_SLUG_SEP, "/") + ".md"


def extract_title(content: str, fallback: str) -> str:
    """Pull the doc title from front-matter or the first H1, else fallback."""
    front = _FRONT_MATTER_TITLE.match(content)
    if front:
        for line in front.group(1).splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("title:"):
                value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    h1 = _H1_LINE.search(content)
    if h1:
        title = h1.group(1).strip()
        if title:
            return title
    return fallback


def scan_docs_root(root: Path) -> list[DocEntry]:
    """Walk `root` recursively and return one DocEntry per `*.md` file.

    Ordering is by relative-path ascending so the listing is stable across
    runs. Hidden files (leading `.`) and any directory whose name starts
    with `.` are skipped — keeps `.git`, `.obsidian`, etc. out of the list.
    """
    if not root.exists() or not root.is_dir():
        return []

    out: list[DocEntry] = []
    for path in root.rglob("*.md"):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            content = ""
        rel = path.relative_to(root).as_posix()
        slug = path_to_slug(rel)
        title = extract_title(content, fallback=path.stem)
        out.append(
            DocEntry(
                slug=slug,
                title=title,
                path=rel,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )

    out.sort(key=lambda e: e.path)
    return out
