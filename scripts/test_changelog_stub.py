#!/usr/bin/env python3
"""Every tracked CHANGELOG.md is byte-identical to the canonical Keep-a-Changelog stub.

Runnable directly from this project (no source packages needed)::

    uv run pytest scripts/test_changelog_stub.py

Running it inside the tai42-skeleton virtualenv is a supported alternative::

    cd tai42/core/skeleton && uv run python -m pytest ../../../tai-docs/scripts/test_changelog_stub.py

Enumeration is ``git ls-files`` over the repo (tracked plus not-yet-committed,
gitignore honoured, so vendored node_modules changelogs are excluded). Any file
whose bytes differ from ``CANONICAL_STUB`` fails the test, and the failure names
each offending path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CANONICAL_STUB = (
    "# Changelog\n"
    "\n"
    "All notable changes to this project will be documented in this file.\n"
    "\n"
    "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),\n"
    "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).\n"
    "\n"
    "## [Unreleased]\n"
)


def _tracked_changelogs() -> list[Path]:
    """Every CHANGELOG.md git sees in the repo (committed or staged/untracked, gitignore honoured)."""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*CHANGELOG.md"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [REPO_ROOT / rel for rel in out.split("\0") if rel]


def test_changelogs_match_canonical_stub() -> None:
    """No CHANGELOG.md in the repo may diverge from the canonical stub."""
    changelogs = _tracked_changelogs()
    assert changelogs, "no CHANGELOG.md found under git in this repo"

    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in changelogs
        if path.read_text(encoding="utf-8") != CANONICAL_STUB
    ]
    assert not offenders, "CHANGELOG.md files diverge from the canonical stub: " + ", ".join(offenders)
    print(f"  {len(changelogs)} CHANGELOG.md byte-identical to the canonical stub")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
