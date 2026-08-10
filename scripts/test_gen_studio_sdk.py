#!/usr/bin/env python3
"""Tests for the Studio SDK reference generator.

Runnable directly (the pinned TypeDoc toolchain under
``scripts/studio_sdk_typedoc/`` and the tai-studio sources must be present)::

    python3 tai-docs/scripts/test_gen_studio_sdk.py

Also collectable by pytest.

Two guarantees are asserted:

1. Checklist coverage — every required public export renders as a heading with a
   signature, and the table-bearing ones (components, interfaces, functions with
   parameters) render a parameters/props table. A missing one is a loud failure,
   guarding against silent under-coverage.
2. Fail-loud — a no-public-exports input (and an empty TypeDoc project) makes the
   generator exit non-zero AND write no placeholder file, so a good reference is
   never overwritten with an empty one.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_studio_sdk as gen  # noqa: E402

# Rendered once and shared across the coverage assertions (TypeDoc is slow-ish).
_PROJECT = None
_PAGES = None
_PAGE_SYMBOLS = None
_ALL_SYMBOLS = None


def _render():
    global _PROJECT, _PAGES, _PAGE_SYMBOLS, _ALL_SYMBOLS
    if _PAGES is None:
        _PROJECT = gen.run_typedoc()
        _PAGES, _PAGE_SYMBOLS, _ALL_SYMBOLS = gen.build_reference(_PROJECT)
    return _PAGES, _PAGE_SYMBOLS, _ALL_SYMBOLS


def test_checklist_coverage() -> None:
    """Every required symbol appears as a heading; table-bearing ones get a table."""
    pages, _page_symbols, symbols = _render()

    missing = [s for s in gen.REQUIRED_SYMBOLS if s not in symbols]
    assert not missing, f"required symbols absent from render: {missing}"

    all_text = "\n".join(pages.values())
    for sym in gen.REQUIRED_SYMBOLS:
        assert f"## {sym}\n" in all_text, f"required symbol {sym!r} not rendered as a heading"
        # Every required symbol carries a signature code block, scoped to this
        # section (up to the next heading) so it can't match a later symbol's block.
        idx = all_text.index(f"## {sym}\n")
        rest = all_text[idx + 1 :]
        nxt = rest.find("\n## ")
        section = rest if nxt < 0 else rest[:nxt]
        assert "```ts" in section, f"required symbol {sym!r} has no signature code block"

    # The table-bearing required symbols render a parameters/props table.
    for sym in gen.REQUIRED_WITH_TABLE:
        idx = all_text.index(f"## {sym}\n")
        # Slice up to the next symbol heading so the check is scoped to this section.
        rest = all_text[idx + 1 :]
        nxt = rest.find("\n## ")
        section = rest if nxt < 0 else rest[:nxt]
        assert "| Parameter |" in section or "| Prop |" in section or "| Property |" in section, (
            f"required symbol {sym!r} rendered without a params/props table"
        )

    print(f"  checklist: all {len(gen.REQUIRED_SYMBOLS)} required symbols present across {len(pages)} pages")
    print(f"            ({len(gen.REQUIRED_WITH_TABLE)} verified to carry a params/props table)")


def test_every_page_has_frontmatter() -> None:
    """Every generated page (index included) carries MDX frontmatter."""
    pages, _page_symbols, _symbols = _render()
    for slug, text in pages.items():
        assert text.startswith("---\n"), f"{slug}: missing frontmatter"
        head = text.split("---", 2)[1]
        for key in ("title:", "description:", "icon:"):
            assert key in head, f"{slug}: frontmatter missing {key}"
    assert "index" in pages, "index page not generated"
    print(f"  frontmatter: all {len(pages)} pages carry title/description/icon")


def test_fail_loud_empty_project() -> None:
    """An empty TypeDoc project -> GenerationError, nothing rendered."""
    empty = {"kind": gen.KIND_PROJECT, "name": "@tai42/studio-sdk", "children": []}
    raised = False
    try:
        gen.build_reference(empty)
    except gen.GenerationError:
        raised = True
    assert raised, "build_reference must raise on a project with no exports"
    print("  fail-loud (empty project): GenerationError raised, nothing rendered")


def test_fail_loud_no_public_exports(tmp_path: Path) -> None:
    """A real entry point with no public exports -> exit 1, no files written.

    Drives the FULL generator (TypeDoc + render + write guard) against a temp
    entry file that exports nothing, proving the fail-loud path never overwrites
    a good reference with an empty one."""
    probe = gen.STUDIO_SDK_DIR / "src" / "__failloud_probe__.ts"
    probe.write_text("// A module with no public exports.\nexport {};\n", encoding="utf-8")

    original_ep = gen.ENTRY_POINTS
    original_out = gen.OUT_DIR
    gen.ENTRY_POINTS = ["src/__failloud_probe__.ts"]
    gen.OUT_DIR = tmp_path
    try:
        rc = gen.main()
    finally:
        gen.ENTRY_POINTS = original_ep
        gen.OUT_DIR = original_out
        probe.unlink(missing_ok=True)

    assert rc == 1, "generator must exit non-zero when there are no public exports"
    written = list(tmp_path.glob("*.mdx"))
    assert not written, f"generator wrote placeholder files on failure: {written}"
    print("  fail-loud (no public exports): exit 1, no files written")


def test_fail_loud_missing_typedoc(tmp_path: Path) -> None:
    """A missing TypeDoc binary -> exit 1 before any write, no files written."""
    original_bin = gen.TYPEDOC_BIN
    original_out = gen.OUT_DIR
    gen.TYPEDOC_BIN = tmp_path / "does-not-exist" / "typedoc"
    gen.OUT_DIR = tmp_path
    try:
        rc = gen.main()
    finally:
        gen.TYPEDOC_BIN = original_bin
        gen.OUT_DIR = original_out

    assert rc == 1, "generator must exit non-zero when the typedoc binary is missing"
    assert not list(tmp_path.glob("*.mdx")), "no files should be written when typedoc is absent"
    print("  fail-loud (missing typedoc): exit 1, no files written")


def main() -> int:
    print("test_gen_studio_sdk:")
    test_checklist_coverage()
    test_every_page_has_frontmatter()
    test_fail_loud_empty_project()
    with tempfile.TemporaryDirectory() as d:
        test_fail_loud_no_public_exports(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_fail_loud_missing_typedoc(Path(d))
    print("test_gen_studio_sdk: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
