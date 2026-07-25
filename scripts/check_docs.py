#!/usr/bin/env python3
"""Static build validation for the docs site (the offline build gate).

The hosted build runs on Mintlify (`mint`), which is not available offline. This
script is the local stand-in: it validates the things a build would catch
without rendering the site.

Checks (all must pass):

  1. ``docs.json`` parses as JSON.
  2. Nav <-> file: every page referenced in the navigation resolves to an
     ``.mdx`` file on disk.
  3. Redirects: every redirect destination resolves to an existing page, and no
     two redirects share a source.
  4. Links resolve: every internal link (Markdown ``](/path)`` and JSX
     ``href="/path"``) in every ``.mdx`` file resolves to a page or a static
     asset. Links inside fenced or inline code are ignored.

It also reports (without failing) any ``.mdx`` file that no nav entry references.

Runs offline with the standard library only::

    python3 scripts/check_docs.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent
DOCS_JSON = DOCS_ROOT / "docs.json"

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_MD_LINK = re.compile(r"\]\((/[^)\s]+)\)")
_HREF = re.compile(r'href="(/[^"]+)"')


def load_docs_json() -> dict:
    try:
        return json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"check_docs: docs.json is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def iter_nav_pages(nav: dict):
    """Yield every page slug referenced in the navigation, at any nesting."""

    def walk(node) -> None:
        if isinstance(node, str):
            yield_pages.append(node)
        elif isinstance(node, dict):
            for page in node.get("pages", []):
                walk(page)
            for group in node.get("groups", []):
                walk(group)
            for tab in node.get("tabs", []):
                walk(tab)

    yield_pages: list[str] = []
    walk(nav)
    return yield_pages


def page_exists(slug: str) -> bool:
    """A nav slug resolves when `<slug>.mdx` or `<slug>/index.mdx` exists."""
    rel = slug.lstrip("/")
    return (DOCS_ROOT / f"{rel}.mdx").is_file() or (DOCS_ROOT / rel / "index.mdx").is_file()


def target_resolves(target: str) -> bool:
    """An internal link/redirect target resolves to a page or a static asset."""
    path = target.split("#", 1)[0].split("?", 1)[0]
    if not path or path == "/":
        return (DOCS_ROOT / "index.mdx").is_file()
    rel = path.lstrip("/")
    candidate = DOCS_ROOT / rel
    return (
        (DOCS_ROOT / f"{rel}.mdx").is_file()
        or (candidate / "index.mdx").is_file()
        or candidate.exists()  # static asset (image, logo, favicon) or directory
    )


def check_nav(docs: dict, problems: list[str]) -> set[str]:
    slugs = iter_nav_pages(docs.get("navigation", {}))
    referenced: set[str] = set()
    for slug in slugs:
        referenced.add(slug.lstrip("/"))
        if not page_exists(slug):
            problems.append(f"nav references '{slug}', but no matching .mdx file exists")
    return referenced


def check_redirects(docs: dict, problems: list[str]) -> None:
    seen: set[str] = set()
    for entry in docs.get("redirects", []):
        source = entry.get("source", "")
        destination = entry.get("destination", "")
        if source in seen:
            problems.append(f"redirect source '{source}' is declared more than once")
        seen.add(source)
        if not target_resolves(destination):
            problems.append(f"redirect '{source}' -> '{destination}' points at a page that does not exist")


def check_links(problems: list[str]) -> int:
    checked = 0
    for mdx in sorted(DOCS_ROOT.rglob("*.mdx")):
        text = mdx.read_text(encoding="utf-8")
        text = _FENCED_CODE.sub("", text)
        text = _INLINE_CODE.sub("", text)
        targets = _MD_LINK.findall(text) + _HREF.findall(text)
        for target in targets:
            checked += 1
            if not target_resolves(target):
                rel = mdx.relative_to(DOCS_ROOT)
                problems.append(f"{rel}: internal link '{target}' does not resolve")
    return checked


def main() -> int:
    docs = load_docs_json()
    problems: list[str] = []

    referenced = check_nav(docs, problems)
    check_redirects(docs, problems)
    link_count = check_links(problems)

    # Orphan pages are a warning, not a failure: the index pages of generated
    # sections are legitimately referenced only through their group.
    orphans = []
    for mdx in sorted(DOCS_ROOT.rglob("*.mdx")):
        slug = str(mdx.relative_to(DOCS_ROOT).with_suffix(""))
        slug_dir = slug[: -len("/index")] if slug.endswith("/index") else slug
        if slug not in referenced and slug_dir not in referenced:
            orphans.append(slug)

    if problems:
        print("check_docs: FAILED -- static validation found problems:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    page_count = len(list(DOCS_ROOT.rglob("*.mdx")))
    print(
        f"check_docs: OK -- docs.json valid, {page_count} pages, "
        f"{len(docs.get('redirects', []))} redirects, {link_count} internal links all resolve."
    )
    if orphans:
        print(f"  note: {len(orphans)} page(s) not referenced by nav: {', '.join(orphans)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
