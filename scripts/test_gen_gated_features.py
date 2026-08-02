#!/usr/bin/env python3
"""Tests for the gated-feature OFF-behavior table generator.

Runnable inside the tai42-skeleton virtualenv, where the skeleton registry the
generator imports resolves::

    cd tai42/core/skeleton && uv run pytest ../../../tai-docs/scripts/test_gen_gated_features.py

Two guarantees are asserted:

1. Coverage — the real skeleton ``_GATED_FEATURES`` registry renders one table row
   per gated feature (with its enabling var and ``off`` kinds-row cell), and that
   table injects cleanly between the concept page's markers.
2. Fail-loud — missing markers, reversed markers, and an empty registry each make
   the generator exit non-zero and write NOTHING (never a blank or partial table).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_gated_features  # noqa: E402

START = gen_gated_features.START_MARKER
END = gen_gated_features.END_MARKER


# --- coverage --------------------------------------------------------------


def test_real_registry_renders_and_injects() -> None:
    """The real skeleton registry yields gated-feature rows that render and inject."""
    features = gen_gated_features._GATED_FEATURES
    assert features, "expected at least one gated feature in the skeleton registry"

    table = gen_gated_features.render_table()
    assert table.startswith("| Feature | Enabling variable(s) | OFF behavior | Kinds row |")
    # One header, one divider, one row per gated feature.
    assert len(table.splitlines()) == len(features) + 2

    # Every feature contributes a row naming its enabling var and its ``off`` kinds row.
    for feature in features:
        assert f"`{feature.enabling_var}`" in table
        assert f"`{feature.kind}` reports `off`" in table

    page = f"intro\n\n{START}\n\nOLD TABLE\n\n{END}\n\noutro\n"
    updated = gen_gated_features.inject(page, table)
    assert table in updated
    assert "OLD TABLE" not in updated
    assert updated.startswith("intro")
    assert updated.endswith("outro\n")
    print(f"  coverage: {len(features)} gated-feature rows rendered and injected")


# --- fail-loud -------------------------------------------------------------


def test_inject_missing_markers_fails_loud() -> None:
    """A page without the markers -> SystemExit(non-zero)."""
    with pytest.raises(SystemExit) as excinfo:
        gen_gated_features.inject("a page with no markers at all", "TABLE")
    assert excinfo.value.code != 0
    print("  fail-loud (missing markers): SystemExit(non-zero)")


def test_inject_reversed_markers_fails_loud() -> None:
    """END before START -> a CLEAN SystemExit, not a bare ValueError."""
    page = f"prose\n{END}\nmiddle\n{START}\nrest"
    with pytest.raises(SystemExit) as excinfo:
        gen_gated_features.inject(page, "TABLE")
    assert excinfo.value.code != 0
    print("  fail-loud (reversed markers): clean SystemExit(non-zero)")


def test_render_table_empty_registry_fails_loud(monkeypatch) -> None:
    """An empty registry -> SystemExit, never a header-only table."""
    monkeypatch.setattr(gen_gated_features, "_GATED_FEATURES", [])
    with pytest.raises(SystemExit) as excinfo:
        gen_gated_features.render_table()
    assert excinfo.value.code != 0
    print("  fail-loud (empty registry): SystemExit(non-zero)")


def test_main_no_partial_write_on_bad_markers(tmp_path: Path, monkeypatch) -> None:
    """main() against a page with reversed markers exits non-zero and leaves the
    page byte-for-byte unchanged (no partial/blank table)."""
    page = tmp_path / "config-and-secrets.mdx"
    original = f"# Page\n\n{END}\n\nreversed\n\n{START}\n"
    page.write_text(original, encoding="utf-8")
    monkeypatch.setattr(gen_gated_features, "PAGE", page)

    with pytest.raises(SystemExit) as excinfo:
        gen_gated_features.main()
    assert excinfo.value.code != 0
    assert page.read_text(encoding="utf-8") == original, "page must be untouched on failure"
    print("  fail-loud (main, reversed markers): no partial write")


def main() -> int:
    print("test_gen_gated_features:")
    test_real_registry_renders_and_injects()
    test_inject_missing_markers_fails_loud()
    test_inject_reversed_markers_fails_loud()
    print("test_gen_gated_features: OK (run under pytest for the monkeypatch cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
