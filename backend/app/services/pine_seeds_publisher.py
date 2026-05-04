"""Optional git publisher for the pine-seeds workspace.

Workflow when ``PINE_SEEDS_REPO_URL`` is configured:

1. ``git init`` (only if ``<workspace>/.git`` is missing).
2. Add or update remote ``origin`` to ``PINE_SEEDS_REPO_URL``.
3. ``git add .``  →  ``git commit -m "newbird snapshot YYYY-MM-DD"``  →
   ``git push -u origin HEAD``.

Authentication is delegated to whatever credential helper / SSH agent the
host has configured — we intentionally do not bake tokens into the URL.
The function is best-effort: any subprocess failure is swallowed and the
reason is returned so the caller can surface it without crashing the
export pipeline.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from app import runtime_settings

logger = logging.getLogger(__name__)


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    """Thin wrapper around ``subprocess.run`` so tests can patch a single name."""
    return subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True)


def _decode_stderr(exc: subprocess.CalledProcessError) -> str:
    stderr = exc.stderr
    if isinstance(stderr, bytes):
        try:
            return stderr.decode("utf-8", errors="replace").strip() or str(exc)
        except Exception:  # noqa: BLE001
            return str(exc)
    if isinstance(stderr, str):
        return stderr.strip() or str(exc)
    return str(exc)


def _is_nothing_to_commit(message: str) -> bool:
    lowered = message.lower()
    return "nothing to commit" in lowered or "nothing added to commit" in lowered


async def publish_workspace(workspace: Path) -> dict[str, Any]:
    """Commit + push ``workspace`` to ``PINE_SEEDS_REPO_URL``.

    Returns one of:
      * ``{"published": False, "reason": "not configured"}`` if the repo URL
        is unset.
      * ``{"published": True}`` on success.
      * ``{"published": True, "reason": "no changes"}`` if there was nothing
        to commit (workspace already up to date).
      * ``{"published": False, "reason": "<stderr or message>"}`` if any git
        subprocess fails.
    """
    repo_url = (runtime_settings.get_setting("PINE_SEEDS_REPO_URL", "") or "").strip()
    if not repo_url:
        return {"published": False, "reason": "not configured"}

    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    git_dir = workspace / ".git"

    # --- git init (only if needed) ---
    if not git_dir.exists():
        try:
            _run(["git", "init"], cwd=workspace)
        except subprocess.CalledProcessError as exc:
            reason = _decode_stderr(exc)
            logger.warning("pine-seeds publish: git init failed: %s", reason)
            return {"published": False, "reason": reason}

    # --- remote add/set-url origin ---
    try:
        _run(["git", "remote", "add", "origin", repo_url], cwd=workspace)
    except subprocess.CalledProcessError:
        # Already exists → switch its URL.
        try:
            _run(["git", "remote", "set-url", "origin", repo_url], cwd=workspace)
        except subprocess.CalledProcessError as exc:
            reason = _decode_stderr(exc)
            logger.warning("pine-seeds publish: remote set-url failed: %s", reason)
            return {"published": False, "reason": reason}

    # --- git add . ---
    try:
        _run(["git", "add", "."], cwd=workspace)
    except subprocess.CalledProcessError as exc:
        reason = _decode_stderr(exc)
        logger.warning("pine-seeds publish: git add failed: %s", reason)
        return {"published": False, "reason": reason}

    # --- git commit ---
    commit_message = f"newbird snapshot {date.today().isoformat()}"
    try:
        _run(["git", "commit", "-m", commit_message], cwd=workspace)
    except subprocess.CalledProcessError as exc:
        reason = _decode_stderr(exc)
        # `git commit` exits non-zero when there's nothing staged — treat as a
        # successful no-op so reruns of the export pipeline don't error out.
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        if _is_nothing_to_commit(reason) or _is_nothing_to_commit(stdout):
            logger.info("pine-seeds publish: nothing to commit — skipping push")
            return {"published": True, "reason": "no changes"}
        logger.warning("pine-seeds publish: git commit failed: %s", reason)
        return {"published": False, "reason": reason}

    # --- git push -u origin HEAD ---
    try:
        _run(["git", "push", "-u", "origin", "HEAD"], cwd=workspace)
    except subprocess.CalledProcessError as exc:
        reason = _decode_stderr(exc)
        logger.warning("pine-seeds publish: git push failed: %s", reason)
        return {"published": False, "reason": reason}

    return {"published": True}
