"""Tests for the docs panel — pure scanner + service against tmp_path."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import docs_service
from core.docs import (
    extract_title,
    path_to_slug,
    scan_docs_root,
    slug_to_path,
)


# ---------- Pure compute ----------


def test_path_to_slug_strips_md_and_replaces_separators():
    assert path_to_slug("a/b/c.md") == "a__b__c"
    assert path_to_slug("plans/2026-04-28-foo.md") == "plans__2026-04-28-foo"
    assert path_to_slug("./a/b.md") == "a__b"


def test_slug_to_path_round_trip():
    assert slug_to_path("a__b__c") == "a/b/c.md"
    assert slug_to_path("plans__2026-04-28-foo") == "plans/2026-04-28-foo.md"


def test_slug_to_path_rejects_traversal_attempts():
    assert slug_to_path("../etc/passwd") is None
    assert slug_to_path("/etc/passwd") is None
    assert slug_to_path("foo bar") is None  # space not in allowlist
    assert slug_to_path("") is None
    # Backslashes should be rejected — we only accept the documented charset
    assert slug_to_path("a\\b") is None


def test_extract_title_prefers_front_matter():
    content = '---\ntitle: "From Front Matter"\nauthor: x\n---\n\n# Header Title\nbody'
    assert extract_title(content, fallback="x") == "From Front Matter"


def test_extract_title_strips_quotes_in_front_matter():
    content = "---\ntitle: 'single quoted'\n---\nbody"
    assert extract_title(content, fallback="x") == "single quoted"


def test_extract_title_falls_back_to_h1():
    content = "# A Real Heading\n\nSome body text."
    assert extract_title(content, fallback="x") == "A Real Heading"


def test_extract_title_falls_back_to_filename():
    assert extract_title("plain body, no heading.", fallback="filename-stem") == "filename-stem"


def test_scan_docs_root_returns_sorted_entries(tmp_path: Path):
    (tmp_path / "a.md").write_text("# Alpha")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("# Bravo")
    (tmp_path / "sub" / "c.md").write_text("body, no heading")
    (tmp_path / "ignore.txt").write_text("not markdown")

    entries = scan_docs_root(tmp_path)
    assert [e.path for e in entries] == ["a.md", "sub/b.md", "sub/c.md"]
    assert entries[0].title == "Alpha"
    assert entries[1].title == "Bravo"
    assert entries[2].title == "c"  # filename fallback


def test_scan_docs_root_skips_hidden_dirs(tmp_path: Path):
    (tmp_path / "shown.md").write_text("# A")
    hidden = tmp_path / ".obsidian"
    hidden.mkdir()
    (hidden / "config.md").write_text("# Hidden")
    (tmp_path / ".dotfile.md").write_text("# Dot")

    entries = scan_docs_root(tmp_path)
    paths = [e.path for e in entries]
    assert "shown.md" in paths
    assert all(".obsidian" not in p for p in paths)
    assert all(".dotfile.md" not in p for p in paths)


def test_scan_docs_root_returns_empty_for_missing_root(tmp_path: Path):
    nope = tmp_path / "does-not-exist"
    assert scan_docs_root(nope) == []


# ---------- Service ----------


class DocsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # tmp dir set up per test below — but Python's IsolatedAsyncioTestCase
        # runs setUp synchronously, so we use class-level _make below.
        pass

    def _make_root(self) -> Path:
        import tempfile

        self._tmp = Path(tempfile.mkdtemp(prefix="docs-test-"))
        (self._tmp / "alpha.md").write_text("# Alpha\nbody")
        (self._tmp / "sub").mkdir()
        (self._tmp / "sub" / "bravo.md").write_text(
            "---\ntitle: Bravo Doc\n---\nbody"
        )
        return self._tmp

    async def test_list_docs_serializes_every_entry(self) -> None:
        root = self._make_root()
        with patch.object(docs_service, "_docs_root", return_value=root):
            payload = await docs_service.list_docs()
        slugs = sorted([item["slug"] for item in payload["items"]])
        self.assertEqual(slugs, ["alpha", "sub__bravo"])
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["root"], str(root))

    async def test_get_doc_returns_content_for_existing_slug(self) -> None:
        root = self._make_root()
        with patch.object(docs_service, "_docs_root", return_value=root):
            payload = await docs_service.get_doc("sub__bravo")
        self.assertEqual(payload["title"], "Bravo Doc")
        self.assertEqual(payload["path"], "sub/bravo.md")
        self.assertIn("body", payload["content"])

    async def test_get_doc_raises_lookup_error_for_missing_slug(self) -> None:
        root = self._make_root()
        with patch.object(docs_service, "_docs_root", return_value=root):
            with self.assertRaisesRegex(LookupError, "Doc not found"):
                await docs_service.get_doc("nope")

    async def test_get_doc_rejects_path_traversal_slug(self) -> None:
        root = self._make_root()
        with patch.object(docs_service, "_docs_root", return_value=root):
            for bad in ["..__etc__passwd", "/etc/passwd", "foo bar", ""]:
                with self.assertRaisesRegex(PermissionError, "Invalid"):
                    await docs_service.get_doc(bad)

    async def test_get_doc_rejects_symlink_escape(self) -> None:
        """A symlink inside the docs root that points outside it should not
        let the caller read the linked file."""
        import os
        import tempfile

        root = self._make_root()
        outside = Path(tempfile.mkdtemp(prefix="docs-outside-"))
        secret = outside / "secret.md"
        secret.write_text("# secret")
        link = root / "sneaky.md"
        try:
            os.symlink(secret, link)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks not supported on this platform")

        with patch.object(docs_service, "_docs_root", return_value=root):
            # The symlink itself appears in the listing under our scanner
            # (because scan_docs_root just rglobs *.md), but get_doc must
            # reject it via the resolved-path check.
            with self.assertRaisesRegex(PermissionError, "Invalid"):
                await docs_service.get_doc("sneaky")
