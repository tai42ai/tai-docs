#!/usr/bin/env python3
"""Tests for the ecosystem catalog generator.

Runnable from this project — the ``dev`` group and the editable sibling sources
resolve the packaged ``ecosystem.yml`` natively::

    uv run pytest scripts/test_gen_catalog.py

Running it inside the tai42-skeleton virtualenv is a supported alternative::

    cd tai42/core/skeleton && uv run python ../../../tai-docs/scripts/test_gen_catalog.py

Two guarantees are asserted:

1. Coverage — every entry in the real packaged ecosystem.yml resolves its
   ``package`` to a source location, and every row lands in the rendered table.
2. Fail-loud — an entry whose ``package`` is absent from the mapping makes the
   generator exit non-zero and write nothing (never a blank source cell).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_catalog  # noqa: E402


def test_every_entry_resolves() -> None:
    """The real packaged file renders and every entry's source appears."""
    doc = gen_catalog.load_ecosystem()
    page = gen_catalog.render(doc)  # raises SystemExit on any unmapped package

    entries = doc["entries"]
    packages = doc["packages"]
    for entry in entries:
        assert entry["package"] in packages, entry["package"]
        source = packages[entry["package"]]
        assert f"`{entry['name']}`" in page, f"row missing for {entry['name']}"
        assert source in page, f"source {source} missing from page"

    assert page.startswith("---\n"), "catalog page missing frontmatter"
    print(f"  coverage: {len(entries)} entries, all packages resolved to a source")


def test_fail_loud_unmapped_package() -> None:
    """An entry whose package is not in the mapping -> SystemExit(non-zero)."""
    doc = copy.deepcopy(gen_catalog.load_ecosystem())
    doc["entries"].append(
        {
            "name": "ghost_tool",
            "kind": "tool",
            "group": "utility",
            "package": "tai-package-with-no-repo",
            "module": "ghost.module",
            "description": "An entry whose package is not in the mapping.",
        }
    )

    with pytest.raises(SystemExit) as excinfo:
        gen_catalog.render(doc)
    assert excinfo.value.code != 0, "unmapped package must exit non-zero"
    print("  fail-loud (unmapped package): SystemExit(non-zero)")


def test_fail_loud_missing_field() -> None:
    """An entry missing a required field -> SystemExit(non-zero)."""
    doc = copy.deepcopy(gen_catalog.load_ecosystem())
    doc["entries"].append({"name": "partial", "kind": "tool", "package": "tai42-skeleton"})
    with pytest.raises(SystemExit) as excinfo:
        gen_catalog.render(doc)
    assert excinfo.value.code != 0, "malformed entry must exit non-zero"
    print("  fail-loud (missing field): SystemExit(non-zero)")


def main() -> int:
    print("test_gen_catalog:")
    test_every_entry_resolves()
    test_fail_loud_unmapped_package()
    test_fail_loud_missing_field()
    print("test_gen_catalog: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
