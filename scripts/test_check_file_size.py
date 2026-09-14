#!/usr/bin/env python3
"""Tests for the module-length cap (standard-library only)::

uv run pytest scripts/test_check_file_size.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_file_size  # noqa: E402


def _write(path: Path, lines: int) -> Path:
    path.write_text("\n".join("x = 1" for _ in range(lines)) + "\n", encoding="utf-8")
    return path


def test_file_at_the_cap_passes(tmp_path: Path) -> None:
    src = _write(tmp_path / "gen_thing.py", check_file_size.MAX_LINES)
    assert check_file_size.oversized_files([src]) == []


def test_file_over_the_cap_is_flagged(tmp_path: Path) -> None:
    src = _write(tmp_path / "gen_thing.py", check_file_size.MAX_LINES + 1)
    offenders = check_file_size.oversized_files([src])
    assert offenders == [(src, check_file_size.MAX_LINES + 1)]


def test_oversized_test_file_is_exempt(tmp_path: Path) -> None:
    src = _write(tmp_path / "test_thing.py", check_file_size.MAX_LINES + 500)
    assert check_file_size.oversized_files([src]) == []


def test_conftest_is_exempt(tmp_path: Path) -> None:
    src = _write(tmp_path / "conftest.py", check_file_size.MAX_LINES + 500)
    assert check_file_size.oversized_files([src]) == []


def test_offenders_sorted_longest_first(tmp_path: Path) -> None:
    small = _write(tmp_path / "gen_small.py", check_file_size.MAX_LINES + 10)
    big = _write(tmp_path / "gen_big.py", check_file_size.MAX_LINES + 50)
    assert [path for path, _ in check_file_size.oversized_files([small, big])] == [big, small]


def test_is_test_file_classification() -> None:
    assert check_file_size.is_test_file(Path("scripts/test_gen_sdk.py"))
    assert check_file_size.is_test_file(Path("scripts/gen_sdk_test.py"))
    assert check_file_size.is_test_file(Path("scripts/conftest.py"))
    assert not check_file_size.is_test_file(Path("scripts/gen_sdk.py"))


def test_committed_tree_is_within_the_cap() -> None:
    assert check_file_size.oversized_files(check_file_size.tracked_python_files(check_file_size.REPO_ROOT)) == []
