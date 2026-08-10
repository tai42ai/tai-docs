#!/usr/bin/env python3
"""Static build validation for the docs site (the offline build gate).

The hosted build runs on Mintlify (`mint`), which is not available offline. This
script is the local stand-in: it validates the things a build would catch
without rendering the site.

Checks (all must pass):

  1. ``docs.json`` parses as JSON.
  2. Nav <-> file: every page referenced in the navigation resolves to an
     ``.mdx`` file on disk.
  3. Redirects: every redirect destination resolves to an existing page, no two
     redirects share a source, and no redirect points at itself.
  4. Links resolve: every internal link (Markdown ``](/path)`` and JSX
     ``href="/path"``) in every ``.mdx`` file resolves to a page or a static
     asset. Links inside fenced or inline code are ignored. The internal
     ``href`` values in ``navbar`` and ``footer`` resolve on the same terms.
  5. Orphans: every ``.mdx`` file is reachable. A page is reachable when the
     navigation lists it, when a navbar or footer link points at it, or when it
     falls in an exempt class (``ORPHAN_EXEMPT``).

Note that the walker sees ``.mdx`` files only -- an unreferenced image is not an
orphan here.

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

# Directories whose pages are reachable without a nav entry. `snippets/` holds
# partials that other pages import -- they render inside their host page and are
# never navigable on their own.
ORPHAN_EXEMPT_DIRS = ("snippets/",)

# Sections whose nav group is rewritten wholesale by a generator (`gen_cli`,
# `gen_sdk`, `gen_studio_sdk`, `gen_plugins`). Their index page belongs to the
# generator, not to the navigation an author edits, so it is reachable by
# construction and exempt from the orphan gate.
GENERATED_INDEX_SLUGS = frozenset(
    {
        "reference/cli/index",
        "reference/python-sdk/index",
        "reference/studio-sdk/index",
        "plugins/index",
    }
)


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


def orphan_exempt(slug: str) -> bool:
    """True when a page is reachable without a navigation entry."""
    return slug.startswith(ORPHAN_EXEMPT_DIRS) or slug in GENERATED_INDEX_SLUGS


def iter_chrome_links(docs: dict):
    """Yield every ``href`` declared in the navbar and the footer, at any nesting.

    These are real entry points into the site: a page linked only from the
    navbar or the footer is navigable, and its links must resolve like any
    other. External hrefs are yielded too; the caller filters them.
    """

    def walk(node) -> None:
        if isinstance(node, dict):
            href = node.get("href")
            if isinstance(href, str):
                hrefs.append(href)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    hrefs: list[str] = []
    walk(docs.get("navbar", {}))
    walk(docs.get("footer", {}))
    return hrefs


def check_chrome_links(docs: dict, problems: list[str]) -> set[str]:
    """Validate navbar/footer internal hrefs and return the pages they reach."""
    referenced: set[str] = set()
    for href in iter_chrome_links(docs):
        if not href.startswith("/"):
            continue  # an external destination -- nothing local to resolve
        if not target_resolves(href):
            problems.append(f"docs.json: navbar/footer link '{href}' does not resolve")
            continue
        referenced.add(href.split("#", 1)[0].split("?", 1)[0].strip("/"))
    return referenced


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
        if source == destination:
            problems.append(f"redirect '{source}' points at itself")
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


def check_orphans(referenced: set[str], problems: list[str]) -> None:
    """Fail on any ``.mdx`` file no navigation entry and no site link reaches."""
    for mdx in sorted(DOCS_ROOT.rglob("*.mdx")):
        slug = str(mdx.relative_to(DOCS_ROOT).with_suffix(""))
        slug_dir = slug[: -len("/index")] if slug.endswith("/index") else slug
        if slug in referenced or slug_dir in referenced or orphan_exempt(slug):
            continue
        problems.append(f"'{slug}' is reachable from neither the navigation nor a navbar/footer link")


def main() -> int:
    docs = load_docs_json()
    problems: list[str] = []

    referenced = check_nav(docs, problems)
    referenced |= check_chrome_links(docs, problems)
    check_redirects(docs, problems)
    link_count = check_links(problems)
    check_orphans(referenced, problems)

    if problems:
        print("check_docs: FAILED -- static validation found problems:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    page_count = len(list(DOCS_ROOT.rglob("*.mdx")))
    print(
        f"check_docs: OK -- docs.json valid, {page_count} pages, "
        f"{len(docs.get('redirects', []))} redirects, {link_count} internal links all resolve, "
        f"every page reachable."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
