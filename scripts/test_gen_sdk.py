#!/usr/bin/env python3
"""Tests for the Python SDK reference generator.

Runnable from this project — the ``dev`` group and the editable sibling sources
resolve the three source packages natively::

    uv run pytest scripts/test_gen_sdk.py

Running it inside the tai-skeleton virtualenv is a supported alternative::

    cd tai-skeleton && uv run python ../tai-docs/scripts/test_gen_sdk.py

Two guarantees are asserted:

1. Checklist coverage — every required public symbol (the Protocols/ABCs, the
   fastmcp escape hatch, and the guarded fetch helper) is rendered. A missing
   one is a loud failure, guarding against silent under-coverage.
2. Fail-loud — a broken input makes the generator exit non-zero AND write no
   placeholder file, so a good reference is never overwritten with an empty one.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_sdk  # noqa: E402


def _fresh_loader():
    return gen_sdk.load_model()


def test_checklist_coverage() -> None:
    """Every required symbol appears in the rendered output and as a heading."""
    loader = _fresh_loader()
    pages, symbols = gen_sdk.build_pages(loader)

    missing = [s for s in gen_sdk.REQUIRED_SYMBOLS if s not in symbols]
    assert not missing, f"required symbols absent from render: {missing}"

    # And each required symbol is a real Markdown heading in some page, so it is
    # navigable — not merely counted.
    all_text = "\n".join(pages.values())
    for sym in gen_sdk.REQUIRED_SYMBOLS:
        assert (f"## {sym}\n" in all_text) or (f"#### {sym}\n" in all_text) or (f"###### {sym}\n" in all_text), (
            f"required symbol {sym!r} not rendered as a heading"
        )

    # Every page carries MDX frontmatter (title/description/icon).
    for slug, text in pages.items():
        assert text.startswith("---\n"), f"{slug}: missing frontmatter"
        for key in ("title:", "description:", "icon:"):
            assert key in text.split("---", 2)[1], f"{slug}: frontmatter missing {key}"

    print(f"  checklist: all {len(gen_sdk.REQUIRED_SYMBOLS)} required symbols present across {len(pages)} pages")


def test_fail_loud_missing_symbol(tmp_path: Path) -> None:
    """A required symbol that cannot be rendered -> exit 1, no files written."""
    original_out = gen_sdk.OUT_DIR
    original_required = gen_sdk.REQUIRED_SYMBOLS
    gen_sdk.OUT_DIR = tmp_path
    gen_sdk.REQUIRED_SYMBOLS = [*original_required, "ThisSymbolDoesNotExist"]
    try:
        rc = gen_sdk.main()
    finally:
        gen_sdk.OUT_DIR = original_out
        gen_sdk.REQUIRED_SYMBOLS = original_required

    assert rc == 1, "generator must exit non-zero when a required symbol is absent"
    written = list(tmp_path.glob("*.mdx"))
    assert not written, f"generator wrote placeholder files on failure: {written}"
    print("  fail-loud (missing symbol): exit 1, no files written")


def test_fail_loud_bad_source(tmp_path: Path) -> None:
    """A missing source path -> exit 1 before any load, no files written."""
    original_src = gen_sdk.SRC_PATHS
    original_out = gen_sdk.OUT_DIR
    gen_sdk.SRC_PATHS = [SCRIPT_DIR / "does-not-exist"]
    gen_sdk.OUT_DIR = tmp_path
    try:
        rc = gen_sdk.main()
    finally:
        gen_sdk.SRC_PATHS = original_src
        gen_sdk.OUT_DIR = original_out

    assert rc == 1, "generator must exit non-zero when a source path is missing"
    assert not list(tmp_path.glob("*.mdx")), "no files should be written on bad source"
    print("  fail-loud (bad source path): exit 1, no files written")


def main() -> int:
    import tempfile

    print("test_gen_sdk:")
    test_checklist_coverage()
    with tempfile.TemporaryDirectory() as d:
        test_fail_loud_missing_symbol(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_fail_loud_bad_source(Path(d))
    print("test_gen_sdk: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
