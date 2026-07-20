#!/usr/bin/env python3
"""Tests for the worked-example snippet sync.

Runnable directly from this project (no source packages needed — it drives the
script against a temporary examples/ tree)::

    uv run pytest scripts/test_sync_examples.py

Running it inside the tai42-skeleton virtualenv is a supported alternative::

    cd tai-skeleton && uv run python -m pytest ../tai-docs/scripts/test_sync_examples.py

Two guarantees are asserted:

1. Coverage — a real example file renders into a snippet whose fenced code block
   carries the file's exact content, and ``--check`` passes when in sync.
2. Fail-loud — a malformed (unparseable) or empty example, a present-but-empty
   examples/ tree, and ``--check`` drift each make the script fail non-zero and
   write no snippet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sync_examples  # noqa: E402


def _wire_tmp(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """Point the script's module-level paths at a temporary tree."""
    examples = tmp_path / "examples"
    snippets = tmp_path / "snippets" / "examples"
    examples.mkdir(parents=True)
    monkeypatch.setattr(sync_examples, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sync_examples, "EXAMPLES_DIR", examples)
    monkeypatch.setattr(sync_examples, "SNIPPETS_DIR", snippets)
    return examples, snippets


def _example(examples: Path, rel: str, code: str) -> Path:
    path = examples / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return path


# --- coverage --------------------------------------------------------------


def test_render_and_check_in_sync(tmp_path: Path, monkeypatch) -> None:
    """A valid example renders into a snippet and --check passes in sync."""
    examples, snippets = _wire_tmp(monkeypatch, tmp_path)
    code = "def greet(name: str) -> str:\n    return f'hi {name}'\n"
    _example(examples, "tool/greet.py", code)

    count = sync_examples.write()
    assert count == 1
    snippet = snippets / "tool" / "greet.mdx"
    assert snippet.exists()
    rendered = snippet.read_text(encoding="utf-8")
    # The fenced block carries the file's exact content and its real path title.
    assert "```python examples/tool/greet.py" in rendered
    assert code in rendered

    assert sync_examples.check() == 0, "freshly written snippets must be in sync"
    assert sync_examples.main(["--check"]) == 0
    print("  coverage: example rendered, --check in sync")


# --- fail-loud -------------------------------------------------------------


def test_malformed_example_fails_loud(tmp_path: Path, monkeypatch) -> None:
    """An example that does not parse as Python -> loud error, no snippet."""
    examples, snippets = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "tool/broken.py", "def broken(:\n")  # syntax error

    with pytest.raises(ValueError, match="does not parse"):
        sync_examples.write()
    assert not snippets.exists() or not list(snippets.rglob("*.mdx")), "no snippet on malformed example"
    print("  fail-loud (malformed example): ValueError, no snippet")


def test_empty_example_file_fails_loud(tmp_path: Path, monkeypatch) -> None:
    """An empty example file -> loud error (never a blank wrapped snippet)."""
    examples, _ = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "tool/blank.py", "   \n")

    with pytest.raises(ValueError, match="is empty"):
        sync_examples.write()
    print("  fail-loud (empty example file): ValueError")


def test_empty_examples_tree_fails_loud(tmp_path: Path, monkeypatch) -> None:
    """A present-but-empty examples/ tree fails in BOTH write and --check modes."""
    _wire_tmp(monkeypatch, tmp_path)  # examples/ exists but has zero .py files
    assert sync_examples.main([]) == 1, "empty examples/ must fail write mode"
    assert sync_examples.main(["--check"]) == 1, "empty examples/ must fail --check"
    print("  fail-loud (empty examples/ tree): exit 1 in both modes")


def test_check_detects_drift(tmp_path: Path, monkeypatch) -> None:
    """A committed snippet that no longer matches its example -> --check exit 1."""
    examples, _ = _wire_tmp(monkeypatch, tmp_path)
    example = _example(examples, "tool/drift.py", "x = 1\n")
    sync_examples.write()
    assert sync_examples.main(["--check"]) == 0

    # Edit the example without re-syncing: the snippet is now stale.
    example.write_text("x = 2\n", encoding="utf-8")
    assert sync_examples.main(["--check"]) == 1, "drifted snippet must fail --check"
    print("  fail-loud (--check drift): exit 1")


def test_check_detects_missing_snippet(tmp_path: Path, monkeypatch) -> None:
    """An example with no committed snippet -> --check exit 1."""
    examples, _ = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "tool/orphan.py", "y = 0\n")
    # Never write() -> the expected snippet is missing.
    assert sync_examples.main(["--check"]) == 1, "missing snippet must fail --check"
    print("  fail-loud (--check missing snippet): exit 1")


# --- multi-kind: shell (CLI/curl) + YAML -----------------------------------


def test_shell_example_renders_bash_fence_and_strips_metadata(tmp_path: Path, monkeypatch) -> None:
    """A .sh example renders as a bash fence; its leading #| metadata block is
    stripped from the rendered snippet, leaving exactly the runnable body."""
    examples, snippets = _wire_tmp(monkeypatch, tmp_path)
    code = "#| fixture: none\n#| expect_exit: 0\ntai keys create --help\n"
    _example(examples, "cli/keys.sh", code)

    sync_examples.write()
    rendered = (snippets / "cli" / "keys.mdx").read_text(encoding="utf-8")
    assert "```bash examples/cli/keys.sh" in rendered
    assert "tai keys create --help" in rendered
    # The metadata block never reaches the page.
    assert "#|" not in rendered
    assert "fixture" not in rendered
    assert sync_examples.check() == 0
    print("  multi-kind (shell): bash fence, metadata stripped, --check in sync")


def test_yaml_example_renders_yaml_fence(tmp_path: Path, monkeypatch) -> None:
    """A .yaml example renders as a yaml fence with its #| block stripped."""
    examples, snippets = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "presets/p.yaml", "#| validate: preset\nbase_tool: echo_tool\n")

    sync_examples.write()
    rendered = (snippets / "presets" / "p.mdx").read_text(encoding="utf-8")
    assert "```yaml examples/presets/p.yaml" in rendered
    assert "base_tool: echo_tool" in rendered
    assert "validate" not in rendered
    print("  multi-kind (yaml): yaml fence, metadata stripped")


def test_malformed_yaml_fails_loud(tmp_path: Path, monkeypatch) -> None:
    """YAML that does not load -> loud error, no snippet."""
    examples, snippets = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "presets/bad.yaml", "#| validate: preset\nkey: : broken\n  - x\n")
    with pytest.raises(ValueError, match="not valid YAML"):
        sync_examples.write()
    assert not snippets.exists() or not list(snippets.rglob("*.mdx"))
    print("  fail-loud (malformed YAML): ValueError, no snippet")


def test_malformed_shell_fails_loud(tmp_path: Path, monkeypatch) -> None:
    """Shell with a syntax error (bash -n) -> loud error, no snippet."""
    examples, snippets = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "cli/bad.sh", "#| fixture: none\nif then fi done\n")
    with pytest.raises(ValueError, match="shell syntax error"):
        sync_examples.write()
    assert not snippets.exists() or not list(snippets.rglob("*.mdx"))
    print("  fail-loud (shell syntax error): ValueError, no snippet")


def test_split_example_parses_metadata_and_body() -> None:
    """The shared splitter separates the #| block from the body cleanly."""
    meta, body = sync_examples.split_example("#| fixture: ac_app\n#| expect_exit: 0\n\ncurl x\n")
    assert meta == {"fixture": "ac_app", "expect_exit": "0"}
    assert body == "curl x\n"
    # A file with no metadata block is all body (the Python path).
    meta2, body2 = sync_examples.split_example("x = 1\n")
    assert meta2 == {}
    assert body2 == "x = 1\n"
    print("  split_example: metadata + body separated; no-metadata file is all body")


def test_snippet_path_collision_fails_loud(tmp_path: Path, monkeypatch) -> None:
    """Two examples sharing a stem (foo.py + foo.sh) both map to foo.mdx -> loud."""
    examples, _ = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "tool/dup.py", "x = 1\n")
    _example(examples, "tool/dup.sh", "#| fixture: none\ntrue\n")
    with pytest.raises(ValueError, match="collision"):
        sync_examples.write()
    print("  fail-loud (snippet path collision): ValueError")


def test_split_example_rejects_colonless_metadata() -> None:
    """A ``#|`` line with no colon is malformed -> loud error (not a silent skip)."""
    with pytest.raises(ValueError, match="malformed metadata line"):
        sync_examples.split_example("#| fixture none\ntai keys create --help\n")
    print("  fail-loud (colonless #| line): ValueError")


def test_split_example_rejects_duplicate_metadata_key() -> None:
    """Two identical ``#|`` keys would last-wins-drop one assertion -> loud error."""
    with pytest.raises(ValueError, match="duplicate metadata key"):
        sync_examples.split_example("#| expect_exit: 0\n#| expect_exit: 1\ntai keys create --help\n")
    print("  fail-loud (duplicate #| key): ValueError")


def test_comment_only_yaml_fails_loud(tmp_path: Path, monkeypatch) -> None:
    """A YAML example whose body is only a comment loads to None -> 'is empty YAML'."""
    examples, snippets = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "presets/comment.yaml", "#| validate: preset\n# only a comment, no document\n")
    with pytest.raises(ValueError, match="is empty YAML"):
        sync_examples.write()
    assert not snippets.exists() or not list(snippets.rglob("*.mdx"))
    print("  fail-loud (comment-only YAML): ValueError")


def test_iter_examples_rejects_unknown_suffix(tmp_path: Path, monkeypatch) -> None:
    """A file with an unrecognized suffix under examples/ -> _iter_examples raises."""
    examples, _ = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "cli/valid.sh", "#| fixture: none\ntrue\n")
    _example(examples, "cli/stray.txt", "not an example\n")
    with pytest.raises(ValueError, match="unrecognized suffix"):
        sync_examples._iter_examples()
    print("  fail-loud (unknown suffix under examples/): ValueError")


def test_iter_examples_ignores_build_noise(tmp_path: Path, monkeypatch) -> None:
    """__pycache__ artifacts and dotfiles are not examples and never trigger the raise."""
    examples, _ = _wire_tmp(monkeypatch, tmp_path)
    _example(examples, "tool/greet.py", "x = 1\n")
    _example(examples, "tool/__pycache__/greet.cpython-312.pyc", "\x00\x00")
    _example(examples, "tool/.hidden.txt", "ignore me\n")
    found = {p.relative_to(examples).as_posix() for p in sync_examples._iter_examples()}
    assert found == {"tool/greet.py"}
    print("  build noise (__pycache__, dotfiles) ignored by _iter_examples")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
