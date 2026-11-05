#!/usr/bin/env python3
"""Tests for the sibling pin refresh (standard-library only)::

uv run pytest scripts/test_refresh_sibling_pins.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import refresh_sibling_pins  # noqa: E402

PYPROJECT = """\
[dependency-groups]
dev = [
    "pytest>=8",
    # a comment naming "alpha" stays as it is
    "alpha>=1,<2",
    "beta[one,two]>=3,<4",
]

[tool.uv.sources]
alpha = { path = "../mono/alpha", editable = true }
beta = { path = "../mono/beta", editable = true }
gamma = { path = "../mono/gamma", editable = true }
"""


def _sibling(root: Path, name: str, version: str) -> None:
    sibling = root.parent / "mono" / name
    sibling.mkdir(parents=True)
    (sibling / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "{version}"\n', encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    checkout = tmp_path / "docs"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return checkout


def test_stated_ranges_move_to_the_sibling_major(root: Path) -> None:
    _sibling(root, "alpha", "7.2.1")
    _sibling(root, "beta", "12.0.0")
    _sibling(root, "gamma", "2.0.0")
    refresh_sibling_pins.refresh(root)
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert '"alpha>=7,<8"' in text
    assert '"beta[one,two]>=12,<13"' in text


def test_everything_else_stays_as_it_is(root: Path) -> None:
    _sibling(root, "alpha", "1.0.0")
    _sibling(root, "beta", "3.0.0")
    _sibling(root, "gamma", "2.0.0")
    refresh_sibling_pins.refresh(root)
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == PYPROJECT


def test_a_missing_sibling_stops_the_run(root: Path) -> None:
    _sibling(root, "alpha", "1.0.0")
    with pytest.raises(FileNotFoundError):
        refresh_sibling_pins.refresh(root)
