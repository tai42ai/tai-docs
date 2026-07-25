#!/usr/bin/env python3
"""Tests for the executable-example harness (run_examples.py).

Run from this project — the ``dev`` group and the editable sibling sources make
the landed contract (the YAML validation path) resolve natively::

    uv run pytest scripts/test_run_examples.py

Running the same test inside the tai42-skeleton virtualenv is a supported
alternative::

    cd tai-skeleton && uv run python -m pytest ../tai-docs/scripts/test_run_examples.py

The heavy ``ac_app`` fixture (a live uvicorn server) is exercised end-to-end by
the docs CI step, not here; these tests drive the harness core against the
zero-cost ``none`` fixture and temporary example trees:

1. discovery fails loudly on an executable example with no ``#|`` block;
2. a shell example's exit-code and stdout expectations are enforced;
3. a YAML example is validated against the landed contract model (valid passes,
   schema-invalid and malformed fail).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import run_examples  # noqa: E402
import sync_examples  # noqa: E402


def _wire_tmp(monkeypatch, tmp_path: Path) -> Path:
    examples = tmp_path / "examples"
    examples.mkdir(parents=True)
    monkeypatch.setattr(sync_examples, "EXAMPLES_DIR", examples)
    return examples


def _example(examples: Path, rel: str, code: str) -> Path:
    path = examples / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return path


# --- discovery -------------------------------------------------------------


def test_discover_requires_metadata_block(tmp_path: Path, monkeypatch) -> None:
    """A .sh example with no #| block is an unasserted example -> loud error."""
    examples = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "cli/nometa.sh", "echo hi\n")
    with pytest.raises(ValueError, match="no '#\\|' metadata block"):
        run_examples.discover()
    print("  discover: unasserted executable example fails loud")


def test_discover_skips_python(tmp_path: Path, monkeypatch) -> None:
    """Python examples are pyright's job, not the executor's — never discovered."""
    examples = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "tool/x.py", "x = 1\n")
    _example(examples, "cli/y.sh", "#| fixture: none\ntrue\n")
    found = {e.rel for e in run_examples.discover()}
    assert found == {"cli/y.sh"}
    print("  discover: python skipped, shell discovered")


# --- shell expectation enforcement -----------------------------------------


def test_shell_pass_and_fail(tmp_path: Path, monkeypatch) -> None:
    examples = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "cli/ok.sh", "#| fixture: none\n#| expect_stdout_contains: hi\necho hi\n")
    _example(examples, "cli/badexit.sh", "#| fixture: none\n#| expect_exit: 0\nexit 3\n")
    _example(examples, "cli/badout.sh", "#| fixture: none\n#| expect_stdout_contains: nope\necho hi\n")

    outcome = run_examples.run(run_examples.discover())
    passed = {r.example.rel for r in outcome.passed}
    failed = {r.example.rel for r in outcome.failed}
    assert passed == {"cli/ok.sh"}
    assert failed == {"cli/badexit.sh", "cli/badout.sh"}
    print("  shell: exit-code and stdout expectations enforced")


def test_unknown_fixture_fails(tmp_path: Path, monkeypatch) -> None:
    examples = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "cli/x.sh", "#| fixture: does_not_exist\ntrue\n")
    outcome = run_examples.run(run_examples.discover())
    assert outcome.failed
    assert "unknown fixture" in outcome.failed[0].detail
    print("  fixture: unknown fixture name fails loud")


# --- YAML validation against the landed contract ---------------------------


def test_yaml_valid_and_invalid(tmp_path: Path, monkeypatch) -> None:
    examples = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "presets/ok.yaml", "#| validate: preset\nbase_tool: echo_tool\n")
    _example(examples, "presets/missing.yaml", "#| validate: preset\ndescription: no base_tool\n")

    outcome = run_examples.run(run_examples.discover())
    passed = {r.example.rel for r in outcome.passed}
    failed = {r.example.rel for r in outcome.failed}
    assert passed == {"presets/ok.yaml"}, "a valid preset validates"
    assert failed == {"presets/missing.yaml"}, "a preset missing base_tool fails"
    print("  yaml: valid preset passes, schema-invalid preset fails")


def test_yaml_requires_validate_target(tmp_path: Path, monkeypatch) -> None:
    """_run_yaml refuses a YAML example with no validate target.

    Discovery's metadata-key allowlist now blocks a stray non-validate key (the
    only way a discovered YAML example could reach _run_yaml without ``validate``)
    up front, so this defensive branch is exercised directly on an Example.
    """
    example = run_examples.Example(
        path=Path("presets/noval.yaml"), suffix=".yaml", meta={}, body="base_tool: echo_tool\n"
    )
    result = run_examples._run_yaml(example)
    assert not result.ok
    assert "must be validated" in result.detail
    print("  yaml: a YAML example with no validate target fails loud")


def test_yaml_non_mapping_body_fails(tmp_path: Path, monkeypatch) -> None:
    """A YAML body that loads to a non-mapping (a list) fails with the mapping message."""
    examples = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "presets/list.yaml", "#| validate: preset\n- one\n- two\n")
    outcome = run_examples.run(run_examples.discover())
    assert outcome.failed
    assert "expected a YAML mapping" in outcome.failed[0].detail
    print("  yaml: a non-mapping YAML body fails loud")


def test_yaml_unknown_validate_target_fails(tmp_path: Path, monkeypatch) -> None:
    """An unknown '#| validate: <bogus>' target fails with the unknown-target message."""
    examples = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "presets/bogus.yaml", "#| validate: bogus\nbase_tool: echo_tool\n")
    outcome = run_examples.run(run_examples.discover())
    assert outcome.failed
    assert "unknown validate target" in outcome.failed[0].detail
    print("  yaml: an unknown validate target fails loud")


def test_yaml_malformed_body_fails(tmp_path: Path, monkeypatch) -> None:
    """A YAML body that is not parseable YAML fails via _run_yaml's yaml.YAMLError branch."""
    examples = _wire_tmp(monkeypatch, tmp_path)
    # Unclosed flow mapping — safe_load raises yaml.YAMLError before any validation.
    _example(examples, "presets/broken.yaml", "#| validate: preset\nbase_tool: {oops\n")
    outcome = run_examples.run(run_examples.discover())
    assert outcome.failed
    assert "not valid YAML" in outcome.failed[0].detail
    print("  yaml: a malformed YAML body fails loud (not valid YAML)")


# --- metadata-key allowlist (discover) -------------------------------------


def test_discover_rejects_unknown_metadata_key(tmp_path: Path, monkeypatch) -> None:
    """An unrecognized #| key (a typo) is a silent-assertion hole -> loud error."""
    examples = _wire_tmp(monkeypatch, tmp_path)
    # ``expct_exit`` is a typo for ``expect_exit``; its assertion would silently vanish.
    _example(examples, "cli/typo.sh", "#| fixture: none\n#| expct_exit: 0\ntrue\n")
    with pytest.raises(ValueError, match="unrecognized '#\\|' metadata key"):
        run_examples.discover()
    print("  discover: an unrecognized metadata key fails loud")


def test_discover_rejects_unknown_yaml_metadata_key(tmp_path: Path, monkeypatch) -> None:
    """A non-``validate`` #| key on a .yaml example hits the YAML_META_KEYS allowlist branch."""
    examples = _wire_tmp(monkeypatch, tmp_path)
    # ``fixture`` is a shell-only key; on a YAML example it is not in YAML_META_KEYS.
    _example(examples, "presets/stray.yaml", "#| validate: preset\n#| fixture: none\nbase_tool: echo_tool\n")
    with pytest.raises(ValueError, match="unrecognized '#\\|' metadata key"):
        run_examples.discover()
    print("  discover: an unrecognized YAML metadata key fails loud")


def test_discover_rejects_empty_stdout_needle(tmp_path: Path, monkeypatch) -> None:
    """An empty expect_stdout_contains needle would always 'pass' -> loud error."""
    examples = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "cli/emptyneedle.sh", "#| fixture: none\n#| expect_stdout_contains:\necho hi\n")
    with pytest.raises(ValueError, match="empty '#\\|' metadata value"):
        run_examples.discover()
    print("  discover: an empty expect_stdout_contains needle fails loud")


def test_yaml_manifest_valid_and_invalid(tmp_path: Path, monkeypatch) -> None:
    """Exercise the manifest model: a valid manifest passes, an explicit-null field fails."""
    examples = _wire_tmp(monkeypatch, tmp_path)
    _example(
        examples,
        "manifest/ok.yaml",
        "#| validate: manifest\nextensions_modules:\n  - tai42_toolbox.extensions.cache\n",
    )
    # ``tools`` is a non-optional list; an explicit null is rejected at validation.
    _example(examples, "manifest/bad.yaml", "#| validate: manifest\ntools: null\n")

    outcome = run_examples.run(run_examples.discover())
    passed = {r.example.rel for r in outcome.passed}
    failed = {r.example.rel for r in outcome.failed}
    assert passed == {"manifest/ok.yaml"}, "a valid manifest validates"
    assert failed == {"manifest/bad.yaml"}, "a manifest with an explicit-null list fails"
    print("  yaml: valid manifest passes, explicit-null-field manifest fails")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
