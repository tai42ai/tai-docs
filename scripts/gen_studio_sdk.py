#!/usr/bin/env python3
"""Generate the Studio SDK reference from ``@tai42/studio-sdk`` via TypeDoc.

This script shells out to a PINNED TypeDoc toolchain (owned by tai-docs, under
``scripts/studio_sdk_typedoc/`` — never a tai-studio dependency) to produce a
JSON object model of the package's PUBLIC export surface, then renders that
model into one MDX reference page per category under ``reference/studio-sdk/``.
Doc comments in the source are the source of truth; every rendered symbol traces
to a real export of a real entry point.

Scope pin: only the package's published entry points are documented —
``.`` (``src/index.ts``), ``./host`` (``src/host.ts``), and ``./testing``
(``src/testing.ts``). Internal/unexported symbols are OUT. The generator
enumerates whatever those entry points export at build time; it never carries a
hard-coded symbol list. Symbols are placed into pages by their source directory,
so a newly exported symbol lands in the matching category automatically.

Owned-renderer pattern (mirrors ``gen_sdk.py``): TypeDoc emits an object model,
not MDX; the JSON -> MDX renderer lives in the ``studio_sdk_ref`` package. Every
page carries MDX frontmatter (title/description/icon); every symbol section
renders a heading, a signature code block, a parameters/props table, cross-links
to related types, and a stable anchor.

Fail-loud contract: the script runs TypeDoc, renders every page into memory, and
validates the required-symbol checklist BEFORE touching the output directory. If
TypeDoc cannot run, if it produces no public exports, or if a required symbol is
missing from the rendered output, it exits non-zero and writes NOTHING — it
never overwrites a good reference with an empty or partial one.

Run it from anywhere (paths are resolved relative to this file)::

    python3 tai-docs/scripts/gen_studio_sdk.py
"""

from __future__ import annotations

import sys

from studio_sdk_ref import config
from studio_sdk_ref.collect import run_typedoc
from studio_sdk_ref.errors import GenerationError
from studio_sdk_ref.nav import build_nav, write_nav
from studio_sdk_ref.pages import _ordered_slugs, build_reference


def main() -> int:
    # 1. Run TypeDoc.
    try:
        project = run_typedoc()
    except GenerationError as exc:
        print(f"gen_studio_sdk: typedoc failed: {exc}", file=sys.stderr)
        return 1

    # 2. Render everything into memory (no filesystem writes yet).
    try:
        pages, page_symbols, all_symbols = build_reference(project)
    except GenerationError as exc:
        print(f"gen_studio_sdk: rendering failed: {exc}", file=sys.stderr)
        return 1

    # 3. Checklist — every required symbol must be present as a rendered heading
    #    with a signature. Fail before writing. (The stricter params/props-table
    #    guarantee is asserted by the test suite, not enforced here.)
    missing = [s for s in config.REQUIRED_SYMBOLS if s not in all_symbols]
    if missing:
        print(
            "gen_studio_sdk: required symbols missing from generated reference: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    all_text = "\n".join(pages.values())
    for sym in config.REQUIRED_SYMBOLS:
        if f"## {sym}\n" not in all_text:
            print(f"gen_studio_sdk: required symbol {sym!r} not rendered as a heading", file=sys.stderr)
            return 1

    # 3b. Build (and validate) the docs.json nav mutation BEFORE any write, so a
    #     malformed docs.json fails the run without leaving pages unwired on disk.
    slugs = _ordered_slugs(page_symbols)
    try:
        nav_data = build_nav(slugs)
    except GenerationError as exc:
        print(f"gen_studio_sdk: docs.json nav update failed: {exc}", file=sys.stderr)
        return 1

    # 4. All checks passed — safe to write. Clean prior generated pages so a
    #    removed category never leaves an orphan page.
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    for existing in config.OUT_DIR.glob("*.mdx"):
        existing.unlink()

    (config.OUT_DIR / "index.mdx").write_text(pages["index"], encoding="utf-8")
    for slug in slugs:
        (config.OUT_DIR / f"{slug}.mdx").write_text(pages[slug], encoding="utf-8")

    write_nav(nav_data)

    total = len(all_symbols)
    print(
        f"gen_studio_sdk: wrote {len(slugs) + 1} pages to {config.OUT_DIR} "
        f"({total} public exports; all {len(config.REQUIRED_SYMBOLS)} required present)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
