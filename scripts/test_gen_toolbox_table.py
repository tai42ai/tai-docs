#!/usr/bin/env python3
"""Tests for the standard-toolbox summary-table generator.

Runnable from this project — the ``dev`` group and the editable sibling sources
resolve the packaged ``ecosystem.yml`` natively::

    uv run pytest scripts/test_gen_toolbox_table.py

Running it inside the tai-skeleton virtualenv is a supported alternative::

    cd tai-skeleton && uv run python ../tai-docs/scripts/test_gen_toolbox_table.py

Two guarantees are asserted:

1. Coverage — the real packaged ecosystem.yml yields the toolbox's tool/extension
   rows, they render into a Markdown table, and that table injects cleanly
   between the guide's markers.
2. Fail-loud — missing markers, reversed markers, no matching rows, and a row
   missing a required field each make the generator exit non-zero and write
   NOTHING (never a blank or partial table).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_toolbox_table  # noqa: E402

START = gen_toolbox_table.START_MARKER
END = gen_toolbox_table.END_MARKER


# --- coverage --------------------------------------------------------------


def test_real_catalog_renders_and_injects() -> None:
    """The real packaged file yields toolbox rows that render and inject."""
    doc = gen_toolbox_table.load_ecosystem()
    rows = gen_toolbox_table.toolbox_rows(doc)  # raises SystemExit on a bad catalog

    assert rows, "expected at least one tai-toolbox tool/extension entry"
    for row in rows:
        assert row["package"] == gen_toolbox_table.TOOLBOX_PACKAGE
        assert row["kind"] in gen_toolbox_table.TOOLBOX_KINDS

    table = gen_toolbox_table.render_table(rows)
    assert table.startswith("| Name | Kind | Summary |")
    # One header, one divider, one row per entry.
    assert len(table.splitlines()) == len(rows) + 2

    guide = f"intro\n\n{START}\n\nOLD TABLE\n\n{END}\n\noutro\n"
    updated = gen_toolbox_table.inject(guide, table)
    assert table in updated
    assert "OLD TABLE" not in updated
    assert updated.startswith("intro")
    assert updated.endswith("outro\n")
    print(f"  coverage: {len(rows)} toolbox rows rendered and injected")


# --- fail-loud -------------------------------------------------------------


def test_inject_missing_markers_fails_loud() -> None:
    """A guide without the markers -> SystemExit(non-zero)."""
    with pytest.raises(SystemExit) as excinfo:
        gen_toolbox_table.inject("a guide with no markers at all", "TABLE")
    assert excinfo.value.code != 0
    print("  fail-loud (missing markers): SystemExit(non-zero)")


def test_inject_reversed_markers_fails_loud() -> None:
    """END before START -> a CLEAN SystemExit, not a bare ValueError.

    Regression guard: an unbounded ``.index(END_MARKER)`` must find the early END
    so the ``end < start`` check fires with the intended diagnostic, rather than
    ``.index(END_MARKER, start)`` raising ``substring not found``.
    """
    guide = f"prose\n{END}\nmiddle\n{START}\nrest"
    with pytest.raises(SystemExit) as excinfo:
        gen_toolbox_table.inject(guide, "TABLE")
    assert excinfo.value.code != 0
    print("  fail-loud (reversed markers): clean SystemExit(non-zero)")


def test_toolbox_rows_no_matching_entries_fails_loud() -> None:
    """A catalog with no tai-toolbox tool/extension entries -> SystemExit."""
    doc = {
        "entries": [
            {
                "name": "other_tool",
                "kind": "tool",
                "package": "some-other-package",
                "description": "Not part of the standard toolbox.",
            }
        ]
    }
    with pytest.raises(SystemExit) as excinfo:
        gen_toolbox_table.toolbox_rows(doc)
    assert excinfo.value.code != 0
    print("  fail-loud (no matching rows): SystemExit(non-zero)")


def test_toolbox_rows_missing_field_fails_loud() -> None:
    """A tai-toolbox entry missing a required field -> SystemExit."""
    doc = {
        "entries": [
            {
                "name": "partial_tool",
                "kind": "tool",
                "package": gen_toolbox_table.TOOLBOX_PACKAGE,
                # 'description' deliberately omitted
            }
        ]
    }
    with pytest.raises(SystemExit) as excinfo:
        gen_toolbox_table.toolbox_rows(doc)
    assert excinfo.value.code != 0
    print("  fail-loud (missing field): SystemExit(non-zero)")


def test_main_no_partial_write_on_bad_markers(tmp_path: Path, monkeypatch) -> None:
    """main() against a guide with reversed markers exits non-zero and leaves the
    guide byte-for-byte unchanged (no partial/blank table)."""
    guide = tmp_path / "standard-toolbox.mdx"
    original = f"# Guide\n\n{END}\n\nreversed\n\n{START}\n"
    guide.write_text(original, encoding="utf-8")
    monkeypatch.setattr(gen_toolbox_table, "GUIDE", guide)

    with pytest.raises(SystemExit) as excinfo:
        gen_toolbox_table.main()
    assert excinfo.value.code != 0
    assert guide.read_text(encoding="utf-8") == original, "guide must be untouched on failure"
    print("  fail-loud (main, reversed markers): no partial write")


def main() -> int:
    print("test_gen_toolbox_table:")
    test_real_catalog_renders_and_injects()
    test_inject_missing_markers_fails_loud()
    test_inject_reversed_markers_fails_loud()
    test_toolbox_rows_no_matching_entries_fails_loud()
    test_toolbox_rows_missing_field_fails_loud()
    print("test_gen_toolbox_table: OK (run under pytest for the tmp_path case)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
