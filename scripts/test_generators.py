#!/usr/bin/env python3
"""Fail-loud tests for the reference generators.

Pins the "a broken generator FAILS, never writes a placeholder" contract:

  * gen_openapi rejects a spec that is not JSON, not OpenAPI 3.1, or has no
    paths, and never overwrites ``openapi.json`` when the emit fails.
  * gen_cli rejects an empty command tree, exits non-zero when extraction
    fails, and the real introspector exits non-zero when the ``tai``
    console-script entry point is absent (the "app can't be resolved" case).

Runs with plain ``python3 scripts/test_generators.py`` (no pytest needed); it is
also collectable by pytest.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_cli
import gen_openapi

SCRIPTS_DIR = Path(__file__).resolve().parent


def _raises(fn, exc=gen_openapi.GenerationError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


# --- gen_openapi -----------------------------------------------------------


def test_validate_spec_rejects_non_json():
    assert _raises(lambda: gen_openapi.validate_spec("not json {"))


def test_validate_spec_rejects_empty_object():
    assert _raises(lambda: gen_openapi.validate_spec("{}"))


def test_validate_spec_rejects_wrong_version():
    spec = json.dumps({"openapi": "3.0.0", "paths": {"/x": {}}})
    assert _raises(lambda: gen_openapi.validate_spec(spec))


def test_validate_spec_rejects_no_paths():
    spec = json.dumps({"openapi": "3.1.0", "paths": {}})
    assert _raises(lambda: gen_openapi.validate_spec(spec))


def test_validate_spec_accepts_valid():
    spec = json.dumps({"openapi": "3.1.0", "paths": {"/api/x": {"get": {}}}})
    parsed = gen_openapi.validate_spec(spec)
    assert parsed["openapi"] == "3.1.0"


def test_gen_openapi_leaves_output_untouched_on_failure():
    """A failed emit must not overwrite an existing openapi.json."""
    output = gen_openapi.OUTPUT
    before = output.read_bytes() if output.exists() else None
    original = gen_openapi.emit_spec

    def boom(_dest):
        raise gen_openapi.GenerationError("simulated emit failure")

    gen_openapi.emit_spec = boom
    try:
        assert gen_openapi.main() == 1
    finally:
        gen_openapi.emit_spec = original
    after = output.read_bytes() if output.exists() else None
    assert before == after


# --- gen_cli ---------------------------------------------------------------


def test_validate_tree_rejects_non_dict():
    assert _raises(lambda: gen_cli.validate_tree([]), gen_cli.GenerationError)


def test_validate_tree_rejects_missing_commands():
    assert _raises(lambda: gen_cli.validate_tree({"name": "tai"}), gen_cli.GenerationError)


def test_validate_tree_rejects_empty_commands():
    tree = {"name": "tai", "commands": []}
    assert _raises(lambda: gen_cli.validate_tree(tree), gen_cli.GenerationError)


def test_validate_tree_accepts_populated():
    tree = {"name": "tai", "commands": [{"name": "x"}]}
    assert gen_cli.validate_tree(tree) is tree


def test_gen_cli_returns_nonzero_when_extraction_fails():
    """When extraction raises, main() exits 1 and writes no pages / nav."""
    docs_before = gen_cli.DOCS_JSON.read_bytes()
    original = gen_cli.extract_tree

    def boom():
        raise gen_cli.GenerationError("simulated extraction failure")

    gen_cli.extract_tree = boom
    try:
        assert gen_cli.main() == 1
    finally:
        gen_cli.extract_tree = original
    assert gen_cli.DOCS_JSON.read_bytes() == docs_before


def test_introspector_fails_loud_without_tai_entry_point():
    """The introspector exits non-zero when the ``tai`` console script is absent.

    Deterministic across environments: rather than relying on the ambient
    interpreter *not* having ``tai42-cli`` installed (false when the suite runs
    inside the skeleton venv), we replace ``importlib.metadata.entry_points`` so
    the console-scripts group carries no ``tai`` entry -- reproducing the real
    "app can't be resolved" failure mode regardless of what is installed.
    """
    introspect = SCRIPTS_DIR / "_cli_introspect.py"
    # Force the console-scripts lookup to return no entries so the introspector's
    # missing-entry-point contract fires, independent of installation.
    bootstrap = (
        "import sys, importlib.metadata; importlib.metadata.entry_points = lambda *a, **k: []; "
        "import runpy; runpy.run_path(sys.argv[1], run_name='__main__')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", bootstrap, str(introspect)],
        cwd=str(SCRIPTS_DIR),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, f"introspector must fail when the tai entry point is absent; stderr={proc.stderr}"
    assert proc.stdout.strip() == ""  # no placeholder tree emitted
    # Pin the *reason*: the missing-entry-point contract fired, not an earlier
    # crash (e.g. ModuleNotFoundError) that would also be non-zero + empty stdout.
    assert "no 'tai' console-script entry point is installed" in proc.stderr, (
        f"expected the missing-entry-point message; stderr={proc.stderr}"
    )


def _run() -> int:
    tests = sorted((name, obj) for name, obj in globals().items() if name.startswith("test_") and callable(obj))
    failures = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"pass {name}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run())
