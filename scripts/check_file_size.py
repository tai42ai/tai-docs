#!/usr/bin/env python3
"""Fail the lint job when a tracked source ``.py`` file grows past the line cap.

Ruff has no whole-module length rule, so this covers that one gap. Test files
carry fixtures and scenario tables that legitimately run long and are exempt;
only the generators and checks under this repository are measured.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

MAX_LINES = 800


def is_test_file(path: Path) -> bool:
    """Whether ``path`` is a test module, which the cap does not measure."""
    name = path.name
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def tracked_python_files(root: Path) -> list[Path]:
    """Every git-tracked ``.py`` file under ``root``, as absolute paths."""
    out = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [root / line for line in out.stdout.splitlines() if line]


def line_count(path: Path) -> int:
    """Number of lines in ``path``."""
    return len(path.read_text(encoding="utf-8").splitlines())


def oversized_files(files: list[Path], max_lines: int = MAX_LINES) -> list[tuple[Path, int]]:
    """The source files whose length exceeds ``max_lines``, longest first."""
    offenders = [(path, line_count(path)) for path in files if not is_test_file(path) and line_count(path) > max_lines]
    return sorted(offenders, key=lambda item: item[1], reverse=True)


def main() -> int:
    offenders = oversized_files(tracked_python_files(REPO_ROOT))
    if offenders:
        print(f"check_file_size: {len(offenders)} source file(s) exceed {MAX_LINES} lines:")
        for path, count in offenders:
            print(f"  {path.relative_to(REPO_ROOT)}: {count} lines")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
