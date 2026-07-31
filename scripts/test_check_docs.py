#!/usr/bin/env python3
"""Tests for the offline build gate.

Runnable straight from this project (the check is standard-library only)::

    uv run pytest scripts/test_check_docs.py

Guarantees asserted:

1. A page no nav entry and no site link reaches is a hard failure.
2. `snippets/` partials and the generator-owned reference indexes are exempt.
3. A navbar or footer link makes its target reachable, and a chrome link that
   resolves to nothing fails.
4. A redirect that points at itself fails.
5. The current committed tree passes every check.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_docs  # noqa: E402


def _tree(root: Path, *slugs: str) -> None:
    """Create an empty ``.mdx`` file for each slug under ``root``."""
    for slug in slugs:
        page = root / f"{slug}.mdx"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("", encoding="utf-8")


def _rooted(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(check_docs, "DOCS_ROOT", root)


# --- orphans ---------------------------------------------------------------


def test_unreachable_page_fails(tmp_path, monkeypatch) -> None:
    """A page outside the nav and outside every exempt class is a failure."""
    _rooted(monkeypatch, tmp_path)
    _tree(tmp_path, "guides/index", "guides/stranded")

    problems: list[str] = []
    check_docs.check_orphans({"guides/index"}, problems)

    assert len(problems) == 1, problems
    assert "guides/stranded" in problems[0]


def test_snippets_and_generated_indexes_are_exempt(tmp_path, monkeypatch) -> None:
    """Partials and generator-owned reference indexes never count as orphans."""
    _rooted(monkeypatch, tmp_path)
    _tree(tmp_path, "snippets/examples/tool/forecast", "reference/cli/index", "reference/catalog/index")

    problems: list[str] = []
    check_docs.check_orphans(set(), problems)

    assert problems == [], problems


def test_index_page_reached_through_its_directory(tmp_path, monkeypatch) -> None:
    """A nav entry naming the directory reaches that directory's index page."""
    _rooted(monkeypatch, tmp_path)
    _tree(tmp_path, "concepts/index")

    problems: list[str] = []
    check_docs.check_orphans({"concepts"}, problems)

    assert problems == [], problems


# --- navbar / footer links -------------------------------------------------


def test_chrome_link_makes_a_page_reachable(tmp_path, monkeypatch) -> None:
    """A page linked only from the footer is navigable, so it is not an orphan."""
    _rooted(monkeypatch, tmp_path)
    _tree(tmp_path, "contributing")
    docs = {"footer": {"links": [{"header": "Project", "items": [{"href": "/contributing"}]}]}}

    problems: list[str] = []
    referenced = check_docs.check_chrome_links(docs, problems)
    check_docs.check_orphans(referenced, problems)

    assert problems == [], problems
    assert referenced == {"contributing"}


def test_external_chrome_link_is_not_a_page(tmp_path, monkeypatch) -> None:
    """An external navbar destination resolves nothing locally and reaches nothing."""
    _rooted(monkeypatch, tmp_path)
    docs = {"navbar": {"links": [{"label": "GitHub", "href": "https://github.com/tai42ai/tai42"}]}}

    problems: list[str] = []
    referenced = check_docs.check_chrome_links(docs, problems)

    assert problems == [], problems
    assert referenced == set()


def test_dangling_chrome_link_fails(tmp_path, monkeypatch) -> None:
    """A navbar link to a page that does not exist is a failure."""
    _rooted(monkeypatch, tmp_path)
    docs = {"navbar": {"primary": {"type": "button", "href": "/getting-started/installation"}}}

    problems: list[str] = []
    check_docs.check_chrome_links(docs, problems)

    assert len(problems) == 1, problems
    assert "/getting-started/installation" in problems[0]


# --- redirects -------------------------------------------------------------


def test_self_redirect_fails(tmp_path, monkeypatch) -> None:
    """A redirect whose source equals its destination is a failure."""
    _rooted(monkeypatch, tmp_path)
    _tree(tmp_path, "operate/deploy")
    docs = {"redirects": [{"source": "/operate/deploy", "destination": "/operate/deploy"}]}

    problems: list[str] = []
    check_docs.check_redirects(docs, problems)

    assert len(problems) == 1, problems
    assert "points at itself" in problems[0]


def test_moved_page_redirect_passes(tmp_path, monkeypatch) -> None:
    """A redirect from a retired path to a real page passes."""
    _rooted(monkeypatch, tmp_path)
    _tree(tmp_path, "operate/deploy")
    docs = {"redirects": [{"source": "/guides/deploy", "destination": "/operate/deploy"}]}

    problems: list[str] = []
    check_docs.check_redirects(docs, problems)

    assert problems == [], problems


# --- whole tree ------------------------------------------------------------


def test_current_tree_passes() -> None:
    """The committed docs tree passes every check, orphans included."""
    docs = check_docs.load_docs_json()
    problems: list[str] = []

    referenced = check_docs.check_nav(docs, problems)
    referenced |= check_docs.check_chrome_links(docs, problems)
    check_docs.check_redirects(docs, problems)
    check_docs.check_links(problems)
    check_docs.check_orphans(referenced, problems)

    assert problems == [], "\n".join(problems)
