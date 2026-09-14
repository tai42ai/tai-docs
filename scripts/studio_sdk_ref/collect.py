"""Acquire and index the TypeDoc model.

Shells out to the pinned TypeDoc toolchain to produce the JSON object model of the
package's public export surface, indexes it by reflection id, and enumerates the
top-level exports across the entry-point modules. The mutable configuration
(entry points, the TypeDoc binary and its inputs) is read through the ``config``
module object at call time so a test that reassigns it is observed here.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from studio_sdk_ref import config
from studio_sdk_ref.errors import GenerationError


def run_typedoc(entry_points: list[str] | None = None) -> dict:
    """Invoke the pinned TypeDoc against the entry points and return the parsed
    project JSON. Raises GenerationError on any failure — a missing binary, a
    TypeDoc error, or output that is not the expected project object."""
    entry_points = entry_points if entry_points is not None else config.ENTRY_POINTS
    if not config.TYPEDOC_BIN.is_file():
        raise GenerationError(
            f"pinned typedoc binary missing: {config.TYPEDOC_BIN}. Run `npm install` in {config.TYPEDOC_DIR}."
        )
    if not config.TSCONFIG.is_file():
        raise GenerationError(f"studio-sdk tsconfig missing: {config.TSCONFIG}")

    with tempfile.TemporaryDirectory() as tmp:
        out_json = Path(tmp) / "studio-sdk.typedoc.json"
        cmd = [
            str(config.TYPEDOC_BIN),
            "--json",
            str(out_json),
            "--tsconfig",
            str(config.TSCONFIG),
            "--entryPointStrategy",
            "resolve",
            "--entryPoints",
            *entry_points,
            "--excludeExternals",
            "--excludePrivate",
            "--excludeInternal",
            "--readme",
            "none",
            "--logLevel",
            "Error",  # warnings (unresolved @links etc.) are non-fatal noise
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(config.STUDIO_SDK_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise GenerationError(f"typedoc exited {proc.returncode}:\n{(proc.stderr or proc.stdout).strip()}")
        if not out_json.is_file():
            raise GenerationError("typedoc produced no JSON output")
        try:
            project = json.loads(out_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise GenerationError(f"typedoc JSON is not valid JSON: {exc}") from exc

    if not isinstance(project, dict) or project.get("kind") != config.KIND_PROJECT:
        raise GenerationError("typedoc output is not a project reflection")
    return project


def index_by_id(project: dict) -> dict[int, dict]:
    """Map every reflection id -> reflection, for resolving numeric references."""
    out: dict[int, dict] = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            if "id" in node and "kind" in node and node.get("variant") == "declaration":
                out[node["id"]] = node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(project)
    return out


def source_dir(refl: dict) -> str:
    """The first path segment under ``src/`` for a reflection's primary source
    (e.g. ``plugin`` for ``.../src/plugin/version.ts``). Returns "" when the
    source lives outside a package ``src/`` tree (a re-exported external type)."""
    sources = refl.get("sources") or []
    if not sources:
        return ""
    file_name = sources[0].get("fileName", "")
    marker = "/src/"
    if marker not in file_name:
        return ""
    return file_name.split(marker, 1)[1].split("/")[0]


def category_for(refl: dict, module_name: str) -> str:
    """The page slug a top-level export belongs to."""
    for cat in config.CATEGORIES:
        if module_name in cat["modules"]:
            return cat["slug"]
    directory = source_dir(refl)
    if directory:
        for cat in config.CATEGORIES:
            if directory in cat["dirs"]:
                return cat["slug"]
    return config.FALLBACK_SLUG


def enumerate_exports(project: dict) -> list[tuple[dict, str]]:
    """Every top-level export across the three entry-point modules, as
    (reflection, module_name). A symbol re-exported from more than one module is
    documented once (first module wins, in module order)."""
    seen: set[str] = set()
    exports: list[tuple[dict, str]] = []
    modules = sorted(
        (m for m in project.get("children", []) if m.get("kind") == config.KIND_MODULE),
        key=lambda m: m.get("name", ""),
    )
    for module in modules:
        module_name = module.get("name", "")
        for child in module.get("children", []) or []:
            name = child.get("name", "")
            if not name or name in seen:
                continue
            # Guard the scope pin: skip anything flagged private/internal.
            flags = child.get("flags") or {}
            if flags.get("isPrivate") or flags.get("isExternal"):
                continue
            seen.add(name)
            exports.append((child, module_name))
    return exports
