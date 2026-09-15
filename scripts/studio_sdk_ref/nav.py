"""docs.json nav wiring for the Studio SDK reference group."""

from __future__ import annotations

import json

from studio_sdk_ref import config
from studio_sdk_ref.errors import GenerationError


def build_nav(slugs: list[str]) -> dict:
    """Parse docs.json and return it mutated with the "Studio SDK" reference group.

    The Reference > "Studio SDK" group is added / refreshed (its pages matching
    the generated files, inserted directly AFTER the Python SDK group). The rest
    of docs.json is preserved byte-for-byte otherwise.

    Raises GenerationError when docs.json has no Reference tab. This is a PURE
    build step run BEFORE any page is written, so a malformed docs.json fails the
    run without leaving partial output on disk; ``write_nav`` performs the write.
    """
    data = json.loads(config.DOCS_JSON.read_text(encoding="utf-8"))
    pages = [f"{config.NAV_PREFIX}/index"] + [f"{config.NAV_PREFIX}/{s}" for s in slugs]
    group = {"group": "Studio SDK", "icon": "puzzle-piece", "pages": pages}

    for tab in data["navigation"]["tabs"]:
        if tab.get("tab") != "Reference":
            continue
        groups = tab["groups"]
        # Replace an existing Studio SDK group in place, else insert after
        # Python SDK (its stable preceding neighbour in the Reference tab).
        for i, existing in enumerate(groups):
            if existing.get("group") == "Studio SDK":
                groups[i] = group
                break
        else:
            insert_at = len(groups)
            for i, existing in enumerate(groups):
                if existing.get("group") == "Python SDK":
                    insert_at = i + 1
                    break
            groups.insert(insert_at, group)
        return data
    raise GenerationError("docs.json: Reference tab not found")


def write_nav(data: dict) -> None:
    """Write the mutated docs.json data produced by ``build_nav``."""
    config.DOCS_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
