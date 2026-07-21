#!/usr/bin/env python3
"""Tests for the hand-written-reference drift-check.

Runnable from this project -- the ``dev`` group and the editable sibling sources
resolve the packaged ``ecosystem.yml`` natively::

    uv run pytest scripts/test_check_docs_refs.py

Running it inside the tai42-skeleton virtualenv is a supported alternative::

    cd tai-skeleton && uv run python ../tai-docs/scripts/test_check_docs_refs.py

Guarantees asserted:

1. A doc naming a real distribution / real repo passes.
2. A fabricated ``tai42-bogus`` distribution fails, naming its ``file:line``.
3. A documented ALWAYS_PUBLIC value that differs from the compose default fails.
4. The current committed tree passes (no drift).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_docs_refs  # noqa: E402


def _dist_map() -> dict[str, str]:
    return check_docs_refs.load_distribution_map()


# --- distribution names ----------------------------------------------------


def test_real_distribution_passes() -> None:
    """A doc naming real distributions produces no problems."""
    dist_map = _dist_map()
    docs = [("fake/install.mdx", "Run `pip install tai42-skeleton` and `uv sync --extra toolbox` for tai42-toolbox.")]
    problems = check_docs_refs.check_distribution_names(docs, set(dist_map))
    assert problems == [], problems
    print("  real distribution names: no problems")


def test_bogus_distribution_fails() -> None:
    """A fabricated tai42-bogus is flagged with its file:line."""
    dist_map = _dist_map()
    docs = [("fake/install.mdx", "line one\nRun `pip install tai42-bogus` here.\n")]
    problems = check_docs_refs.check_distribution_names(docs, set(dist_map))
    assert len(problems) == 1, problems
    assert problems[0].startswith("fake/install.mdx:2:"), problems[0]
    assert "tai42-bogus" in problems[0]
    print("  bogus distribution: flagged at file:line")


def test_logo_asset_not_mistaken_for_distribution() -> None:
    """The `/tai42-logo-icon.png` asset path is not read as a distribution name."""
    dist_map = _dist_map()
    docs = [("fake/deploy.mdx", 'PREFIXES=\'["/tai42-logo-icon.png", "/"]\'')]
    problems = check_docs_refs.check_distribution_names(docs, set(dist_map))
    assert problems == [], problems
    print("  logo asset path: not mistaken for a distribution")


# --- repo URLs -------------------------------------------------------------


def test_real_repo_url_passes() -> None:
    """A package-repo URL resolves against the distribution->repo mapping."""
    dist_map = _dist_map()
    docs = [("fake/x.mdx", "git clone https://github.com/tai42ai/tai-skeleton")]
    problems, _notes = check_docs_refs.check_repo_urls(docs, dist_map)
    assert problems == [], problems
    print("  real repo URL: no problems")


# --- ALWAYS_PUBLIC ---------------------------------------------------------


def test_mismatched_always_public_fails() -> None:
    """A documented ALWAYS_PUBLIC value that differs from the default fails."""
    default = ["/api/login", "/assets", "/"]
    docs = [("fake/deploy.mdx", "x\nexport ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES='[\"/api/login\"]'\n")]
    problems = check_docs_refs.compare_always_public(docs, default)
    assert len(problems) == 1, problems
    assert problems[0].startswith("fake/deploy.mdx:2:"), problems[0]
    print("  mismatched ALWAYS_PUBLIC: flagged at file:line")


def test_matching_always_public_passes() -> None:
    """A documented ALWAYS_PUBLIC value equal to the default passes."""
    default = ["/api/login", "/assets", "/"]
    value = 'export ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES=\'["/api/login", "/assets", "/"]\''
    docs = [("fake/deploy.mdx", value)]
    problems = check_docs_refs.compare_always_public(docs, default)
    assert problems == [], problems
    print("  matching ALWAYS_PUBLIC: no problems")


# --- whole tree ------------------------------------------------------------


def test_current_tree_passes() -> None:
    """The committed docs tree has no reference drift (problems empty)."""
    problems, notes = check_docs_refs.evaluate()
    assert problems == [], "\n".join(problems)
    print(f"  current tree: no drift ({len(notes)} offline-gated note(s))")


def main() -> int:
    print("test_check_docs_refs:")
    test_real_distribution_passes()
    test_bogus_distribution_fails()
    test_logo_asset_not_mistaken_for_distribution()
    test_real_repo_url_passes()
    test_mismatched_always_public_fails()
    test_matching_always_public_passes()
    test_current_tree_passes()
    print("test_check_docs_refs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
