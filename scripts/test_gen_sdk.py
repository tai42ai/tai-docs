#!/usr/bin/env python3
"""Tests for the Python SDK reference generator.

Runnable from this project — the ``dev`` group and the editable sibling sources
resolve the three source packages natively::

    uv run pytest scripts/test_gen_sdk.py

Running it inside the tai42-skeleton virtualenv is a supported alternative::

    cd tai42/core/skeleton && uv run python ../../../tai-docs/scripts/test_gen_sdk.py

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


def test_later_module_docstring_renders_before_its_first_symbol() -> None:
    """A later listed module's docstring renders as a prose block before its first symbol.

    Pinned against the real ``kit-llm`` page: its second module
    ``tai42_kit.llm.classifier`` contributes ``QuestionContent`` (and the other
    contract models) as not-yet-seen symbols, so the classifier module's first
    doc section renders immediately above that module's first rendered heading.
    """
    loader = _fresh_loader()
    spec = next(s for s in gen_sdk.PAGES if s["slug"] == "kit-llm")
    text, _ = gen_sdk.render_page(loader, spec)

    classifier = loader.modules_collection["tai42_kit.llm.classifier"]
    lead_line = gen_sdk._doc_sections(classifier)[0].splitlines()[0]
    assert lead_line, "the classifier module must have a docstring to render"

    lead_pos = text.find(lead_line)
    symbol_pos = text.find("## QuestionContent\n")
    assert lead_pos != -1, "classifier module docstring did not render on the kit-llm page"
    assert symbol_pos != -1, "QuestionContent did not render as a heading"
    assert lead_pos < symbol_pos, "classifier module docstring must render before its first symbol heading"
    print("  later-module docstring: rendered before its first symbol")


def test_fully_deduped_later_module_adds_no_prose() -> None:
    """A later module whose every symbol was already rendered adds no orphan prose block.

    A page that lists the same module twice renders every symbol under the first
    listing; the second listing contributes no not-yet-seen symbol, so its
    docstring must not be emitted a second time.
    """
    loader = _fresh_loader()
    spec = {
        "slug": "dedup-probe",
        "title": "Dedup probe",
        "description": "A page listing one module twice.",
        "icon": "brain",
        "modules": ["tai42_kit.llm.classifier", "tai42_kit.llm.classifier"],
    }
    text, _ = gen_sdk.render_page(loader, spec)

    classifier = loader.modules_collection["tai42_kit.llm.classifier"]
    lead_line = gen_sdk._doc_sections(classifier)[0].splitlines()[0]
    assert text.count(lead_line) == 1, "a fully deduped later module must not re-emit its docstring prose block"
    assert text.count("## QuestionContent\n") == 1, "the deduped symbol must render only once"
    print("  fully-deduped later module: no orphan prose block")


def test_setext_heading_in_prose_becomes_bold() -> None:
    """An RST setext heading in prose folds to ``**Heading**`` and loses its rule.

    A section title underlined with dashes would otherwise render as a Markdown
    setext H2 and enter the page's on-page table of contents beside the SDK
    symbols; the fold keeps it as emphasised text with a blank line before the
    body.
    """
    text = "Intro paragraph.\n\nMy Heading\n----------\nBody text here.\n"
    out = gen_sdk.mdx_escape_prose(text)
    assert "**My Heading**" in out, "setext heading not folded to bold"
    assert "----------" not in out, "setext underline line not dropped"
    assert "**My Heading**\n\nBody text here." in out, "no blank line between heading and body"
    print("  setext heading in prose: folded to bold, underline dropped")


def test_thematic_break_after_blank_line_preserved() -> None:
    """A dash rule that follows a blank line is a thematic break, left as is."""
    text = "Paragraph one.\n\n---\n\nParagraph two.\n"
    out = gen_sdk.mdx_escape_prose(text)
    assert "\n---\n" in out, "thematic break after a blank line must be preserved"
    assert "**" not in out, "a thematic break must not become bold text"
    print("  thematic break after blank line: preserved")


def test_setext_underline_inside_fence_preserved() -> None:
    """A dash line inside a fenced code block is verbatim, never a heading."""
    text = "Example:\n\n```\nHeading\n-------\n```\n"
    out = gen_sdk.mdx_escape_prose(text)
    assert "```\nHeading\n-------\n```" in out, "fenced dash line must pass through verbatim"
    assert "**Heading**" not in out, "a fenced dash line must not be folded to bold"
    print("  setext underline inside fence: preserved")


def test_contract_monitoring_setext_heading_becomes_bold() -> None:
    """The regenerated contract-monitoring page carries no setext underline.

    The writer module docstring's ``FAIL-SAFE INVARIANT`` section title renders
    as bold, and no dash-only line preceded by a non-blank text line survives
    outside the frontmatter (whose closing ``---`` follows the icon line).
    """
    loader = _fresh_loader()
    spec = next(s for s in gen_sdk.PAGES if s["slug"] == "contract-monitoring")
    text, _ = gen_sdk.render_page(loader, spec)

    assert "**FAIL-SAFE INVARIANT**" in text, "writer section title not folded to bold"

    body = text.split("---", 2)[2]  # drop the frontmatter block
    lines = body.split("\n")
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        is_dash_rule = len(stripped) >= 3 and set(stripped) == {"-"}
        if is_dash_rule:
            assert not (i > 0 and lines[i - 1].strip()), (
                f"setext underline survived under {lines[i - 1]!r} at body line {i}"
            )
    print("  contract-monitoring page: heading bold, no setext underline in body")


def main() -> int:
    import tempfile

    print("test_gen_sdk:")
    test_checklist_coverage()
    test_later_module_docstring_renders_before_its_first_symbol()
    test_fully_deduped_later_module_adds_no_prose()
    test_setext_heading_in_prose_becomes_bold()
    test_thematic_break_after_blank_line_preserved()
    test_setext_underline_inside_fence_preserved()
    test_contract_monitoring_setext_heading_becomes_bold()
    with tempfile.TemporaryDirectory() as d:
        test_fail_loud_missing_symbol(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_fail_loud_bad_source(Path(d))
    print("test_gen_sdk: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
