#!/usr/bin/env python3
"""Tests for the standard-toolbox summary-table generator.

Runnable from this project — the ``dev`` group resolves the committed
``plugins/_registry.json`` snapshot natively::

    uv run pytest scripts/test_gen_toolbox_table.py

Two guarantees are asserted:

1. Coverage — the committed registry yields the toolbox's tool/extension item
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

TOOLBOX = gen_toolbox_table.TOOLBOX_PACKAGE


def _listing(package: str, items: list[dict]) -> dict:
    return {
        "namespace": "tai42",
        "name": package.removeprefix("tai42-"),
        "package": package,
        "premium": False,
        "items": items,
    }


# --- coverage --------------------------------------------------------------


def test_real_registry_renders_and_injects() -> None:
    """The committed registry yields toolbox rows that render and inject."""
    listings = gen_toolbox_table.load_registry()
    rows = gen_toolbox_table.toolbox_rows(listings)  # raises SystemExit on a bad registry

    assert rows, "expected at least one tai42-toolbox tool/extension item"
    for row in rows:
        assert row["kind"] in gen_toolbox_table.TOOLBOX_KINDS

    table = gen_toolbox_table.render_table(rows)
    assert table.startswith("| Name | Kind | Summary |")
    # One header, one divider, one row per item.
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
    """END before START -> a CLEAN SystemExit, not a bare ValueError."""
    guide = f"prose\n{END}\nmiddle\n{START}\nrest"
    with pytest.raises(SystemExit) as excinfo:
        gen_toolbox_table.inject(guide, "TABLE")
    assert excinfo.value.code != 0
    print("  fail-loud (reversed markers): clean SystemExit(non-zero)")


def test_toolbox_rows_no_matching_entries_fails_loud() -> None:
    """A registry with no tai42-toolbox tool/extension items -> SystemExit."""
    listings = [_listing("some-other-package", [{"kind": "tool", "name": "other", "description": "Not the toolbox."}])]
    with pytest.raises(SystemExit) as excinfo:
        gen_toolbox_table.toolbox_rows(listings)
    assert excinfo.value.code != 0
    print("  fail-loud (no matching rows): SystemExit(non-zero)")


def test_toolbox_rows_missing_field_fails_loud() -> None:
    """A tai42-toolbox item missing a required field -> SystemExit."""
    listings = [_listing(TOOLBOX, [{"kind": "tool", "name": "partial"}])]  # no description
    with pytest.raises(SystemExit) as excinfo:
        gen_toolbox_table.toolbox_rows(listings)
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
    test_real_registry_renders_and_injects()
    test_inject_missing_markers_fails_loud()
    test_inject_reversed_markers_fails_loud()
    test_toolbox_rows_no_matching_entries_fails_loud()
    test_toolbox_rows_missing_field_fails_loud()
    print("test_gen_toolbox_table: OK (run under pytest for the tmp_path case)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
