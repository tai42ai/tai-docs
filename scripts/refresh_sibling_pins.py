#!/usr/bin/env python3
"""Move the dev group's compatible ranges to the versions of the sibling checkouts.

Every package ``[tool.uv.sources]`` points at a sibling path, and the dev group
states a compatible range for it, gets the range of that sibling's current major
(``>=N,<N+1``). A package the sources name but the dev group does not state is left
alone. A sibling that cannot be read stops the run with an error. The refresh
workflow runs this and then ``uv lock --upgrade``::

    python scripts/refresh_sibling_pins.py
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


def sibling_majors(root: Path, sources: dict[str, dict[str, object]]) -> dict[str, int]:
    """The major version of each path source, read from the sibling's ``pyproject.toml``."""
    majors: dict[str, int] = {}
    for name, source in sources.items():
        path = source.get("path")
        if not isinstance(path, str):
            continue
        project = tomllib.loads((root / path / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        majors[name] = int(project["version"].split(".")[0])
    return majors


def with_ranges(text: str, majors: dict[str, int]) -> str:
    """``text`` with each stated range of a package in ``majors`` set to that package's major."""
    for name, major in majors.items():
        text = re.sub(
            rf'("{re.escape(name)}(?:\[[^\]]*\])?)>=[^"]*"',
            rf'\g<1>>={major},<{major + 1}"',
            text,
        )
    return text


def refresh(root: Path) -> None:
    """Rewrite ``root/pyproject.toml`` so its dev group ranges match the sibling checkouts."""
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(
        with_ranges(text, sibling_majors(root, tomllib.loads(text)["tool"]["uv"]["sources"])),
        encoding="utf-8",
    )


if __name__ == "__main__":
    refresh(REPO_ROOT)
