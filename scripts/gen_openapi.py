#!/usr/bin/env python3
"""Generate the HTTP API reference spec (``openapi.json``).

Runs the tai42-skeleton offline OpenAPI emitter (``tai openapi --out``) and writes
the resulting OpenAPI 3.1 document to ``openapi.json`` at the repo root, where
Mintlify renders the HTTP API section natively from the ``openapi`` field in
``docs.json``.

The emitter builds the spec from the app's registered routes without booting a
server, database, or Redis, so this runs offline in CI.

Fail-loud contract: the spec is emitted to a temporary file and validated
(parses as JSON, declares OpenAPI 3.1, carries at least one path) before it
replaces ``openapi.json``. If the emit fails or the spec is empty or invalid,
this exits non-zero and leaves the existing ``openapi.json`` untouched -- it
never overwrites a good reference with junk.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent
SKELETON_DIR = DOCS_ROOT.parent / "tai-skeleton"
OUTPUT = DOCS_ROOT / "openapi.json"


class GenerationError(RuntimeError):
    """A generation step failed; nothing was written."""


def emit_spec(dest: Path) -> None:
    """Run the skeleton emitter, writing the raw spec to ``dest``.

    Raises GenerationError if the skeleton package or the emitter is missing,
    or the command exits non-zero.
    """
    if not SKELETON_DIR.is_dir():
        raise GenerationError(f"tai42-skeleton checkout not found at {SKELETON_DIR}")
    try:
        proc = subprocess.run(
            ["uv", "run", "tai", "openapi", "--out", str(dest)],
            cwd=SKELETON_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # uv not installed
        raise GenerationError(f"could not launch the emitter: {exc}") from exc
    if proc.returncode != 0:
        raise GenerationError(
            f"the emitter (`tai openapi`) exited {proc.returncode}:\n{proc.stderr.strip() or proc.stdout.strip()}"
        )
    if not dest.exists() or dest.stat().st_size == 0:
        raise GenerationError("the emitter wrote no spec")


def validate_spec(text: str) -> dict:
    """Parse and sanity-check the emitted spec.

    Raises GenerationError unless the text is valid JSON, declares OpenAPI 3.1,
    and carries at least one path. Returns the parsed document.
    """
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"emitted spec is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise GenerationError("emitted spec is not a JSON object")
    version = str(spec.get("openapi", ""))
    if not version.startswith("3.1"):
        raise GenerationError(f"emitted spec declares OpenAPI {version!r}, expected 3.1.x")
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise GenerationError("emitted spec has no paths")
    return spec


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "openapi.json"
        try:
            emit_spec(staged)
            spec = validate_spec(staged.read_text(encoding="utf-8"))
        except GenerationError as exc:
            print(f"gen_openapi: FAILED -- {exc}", file=sys.stderr)
            print("gen_openapi: openapi.json left untouched", file=sys.stderr)
            return 1
        # Pretty-print for a readable diff in the committed reference.
        OUTPUT.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"gen_openapi: wrote {OUTPUT.relative_to(DOCS_ROOT)} ({len(spec['paths'])} paths, OpenAPI {spec['openapi']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
