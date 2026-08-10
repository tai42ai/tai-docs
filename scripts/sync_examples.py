"""Sync the docs' worked examples into importable Mintlify snippets.

A page never inlines a worked example as prose. Each worked example lives as a
single source file under ``examples/<group>/…`` (the single source of truth,
verified in CI), and this script renders each one into a snippet under
``snippets/examples/<same path>.mdx`` that wraps the file's exact content in a
fenced code block. The pages that use an example import its generated snippet, so
what renders on the page is always the real, verified file.

Three example kinds are supported, keyed by file suffix:

* ``.py`` — a Python plugin/author example, type-checked by pyright in CI and
  rendered as a ``python`` fence.
* ``.sh`` — a CLI (``tai …``) or ``curl`` operator example, rendered as a
  ``bash`` fence and EXECUTED by ``run_examples.py`` in CI.
* ``.yaml`` / ``.yml`` — a manifest/preset example, rendered as a ``yaml`` fence
  and validated against the landed contract model by ``run_examples.py`` in CI.

Executable examples (``.sh`` / ``.yaml``) may carry a leading metadata block of
``#|``-prefixed comment lines (``#| key: value``) that declares the expected
runtime outcome for ``run_examples.py``. That block is STRIPPED from the rendered
snippet, so the operator-facing page shows only the runnable body. Python
examples carry no metadata block.

Usage::

    python scripts/sync_examples.py            # (re)generate snippets/examples/
    python scripts/sync_examples.py --check     # verify snippets are in sync

``--check`` regenerates into memory and diffs against the committed snippets,
exiting non-zero on any drift (a changed, missing, or stale snippet). It is the
anti-rot gate: a contract change that alters an example, or an edit to an example
that was not synced, fails the build. A malformed example (Python that does not
parse, YAML that does not load, shell with a syntax error) fails loudly in either
mode, and so does a present-but-empty ``examples/`` tree (zero discovered files)
— an emptied examples/ is a regression, never a valid state that passes clean.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

import yaml

# Repo layout: this file is <repo>/scripts/sync_examples.py.
REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
SNIPPETS_DIR = REPO_ROOT / "snippets" / "examples"

GENERATED_NOTICE = "Generated from {source} by scripts/sync_examples.py. Do not edit."

# Every example suffix -> the fenced-code language it renders as. A file under
# examples/ with any other suffix is a mistake (a stray sidecar, a wrong
# extension) and is never silently ignored: _iter_examples RAISES on it. The only
# thing skipped is build noise (``__pycache__`` directories and dotfiles), which
# is not an example.
SUFFIX_LANG = {
    ".py": "python",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
}

# The leading-metadata sigil for executable examples. Lines like ``#| key: value``
# at the top of a .sh/.yaml example declare the runtime expectation consumed by
# run_examples.py; they are stripped from the rendered snippet.
META_SIGIL = "#|"


def _iter_examples() -> list[Path]:
    """Every example source file, sorted for deterministic output.

    A file under ``examples/`` whose suffix is not in :data:`SUFFIX_LANG` is a
    mistake (a stray sidecar, a mis-suffixed example) and RAISES loudly — silently
    skipping it is exactly the doc-rot this harness exists to prevent. Build noise
    is not an example and is ignored: any path segment that is a ``__pycache__``
    directory or a dotfile (a leading ``.`` on the file or a parent) never triggers,
    so a compiled ``.pyc`` or a hidden sidecar does not false-fail the gate.
    """
    result: list[Path] = []
    for path in sorted(EXAMPLES_DIR.rglob("*")):
        if not path.is_file():
            continue
        if any(part == "__pycache__" or part.startswith(".") for part in path.relative_to(EXAMPLES_DIR).parts):
            continue
        if path.suffix not in SUFFIX_LANG:
            raise ValueError(
                f"example {path} has an unrecognized suffix {path.suffix!r} — every file under "
                f"{EXAMPLES_DIR.name}/ must be one of {sorted(SUFFIX_LANG)} (a mis-suffixed or stray "
                f"file is doc-rot, never silently skipped)"
            )
        result.append(path)
    return result


def split_example(text: str) -> tuple[dict[str, str], str]:
    """Split an example's raw text into ``(metadata, body)``.

    The metadata is the block of contiguous leading ``#| key: value`` comment
    lines (the executable-example expectation declaration); the body is the rest,
    with the blank lines between the block and the body stripped. A file with no
    ``#|`` block (every Python example) yields an empty metadata dict and the full
    text as the body. Shared with ``run_examples.py`` so the render and the
    executor read the SAME split from one implementation.
    """
    lines = text.splitlines(keepends=True)
    meta: dict[str, str] = {}
    idx = 0
    for idx, line in enumerate(lines):  # noqa: B007
        stripped = line.strip()
        if not stripped.startswith(META_SIGIL):
            break
        entry = stripped[len(META_SIGIL) :].strip()
        if entry:
            if ":" not in entry:
                raise ValueError(f"malformed metadata line (want '#| key: value'): {line!r}")
            key, _, value = entry.partition(":")
            if key.strip() in meta:
                raise ValueError(
                    f"duplicate metadata key {key.strip()!r} — declared twice, one assertion would be silently dropped"
                )
            meta[key.strip()] = value.strip()
    else:
        # Every line was metadata (no body). Advance past the last line.
        idx = len(lines)

    body_lines = lines[idx:]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    return meta, "".join(body_lines)


def _validate(source: Path, suffix: str, body: str) -> None:
    """Fail loudly if the example body is malformed for its kind.

    A broken example must never be silently wrapped and shipped: Python must
    parse, YAML must load to a non-empty document, and shell must pass a
    ``bash -n`` syntax check.
    """
    if suffix == ".py":
        try:
            ast.parse(body, filename=str(source))
        except SyntaxError as exc:
            raise ValueError(f"example {source} does not parse: {exc}") from exc
    elif suffix in (".yaml", ".yml"):
        try:
            loaded = yaml.safe_load(body)
        except yaml.YAMLError as exc:
            raise ValueError(f"example {source} is not valid YAML: {exc}") from exc
        if loaded is None:
            raise ValueError(f"example {source} is empty YAML")
    elif suffix == ".sh":
        proc = subprocess.run(["bash", "-n"], input=body, text=True, capture_output=True, check=False)
        if proc.returncode != 0:
            raise ValueError(f"example {source} has a shell syntax error: {proc.stderr.strip()}")
    else:  # pragma: no cover - guarded by _iter_examples's suffix filter
        raise ValueError(f"example {source} has an unsupported suffix {suffix!r}")


def _render_snippet(source: Path) -> str:
    """Render one example file into its snippet MDX content."""
    suffix = source.suffix
    lang = SUFFIX_LANG.get(suffix)
    if lang is None:  # pragma: no cover - guarded by _iter_examples
        raise ValueError(f"example {source} has an unsupported suffix {suffix!r}")

    text = source.read_text(encoding="utf-8")
    _, body = split_example(text)
    if not body.strip():
        raise ValueError(f"example {source} is empty")
    _validate(source, suffix, body)

    rel = source.relative_to(REPO_ROOT).as_posix()
    body = body if body.endswith("\n") else body + "\n"
    notice = GENERATED_NOTICE.format(source=rel)
    # An MDX comment ({/* … */}) is carried into the imported snippet without
    # rendering; the code fence's title shows readers the real file path.
    return f"{{/* {notice} */}}\n\n```{lang} {rel}\n{body}```\n"


def _snippet_path_for(source: Path) -> Path:
    return SNIPPETS_DIR / source.relative_to(EXAMPLES_DIR).with_suffix(".mdx")


def _expected() -> dict[Path, str]:
    """Map every expected snippet path to its rendered content.

    Two examples that share a stem (``foo.py`` + ``foo.sh``) would both map to
    ``foo.mdx`` and silently clobber one another; that collision is a loud error,
    not a coin toss over which snippet ships.
    """
    result: dict[Path, str] = {}
    owner: dict[Path, Path] = {}
    for src in _iter_examples():
        target = _snippet_path_for(src)
        if target in owner:
            raise ValueError(
                f"snippet path collision: {src} and {owner[target]} both render to {target.relative_to(REPO_ROOT)}"
            )
        owner[target] = src
        result[target] = _render_snippet(src)
    return result


def _existing_snippets() -> set[Path]:
    if not SNIPPETS_DIR.exists():
        return set()
    return {p for p in SNIPPETS_DIR.rglob("*.mdx") if p.is_file()}


def write() -> int:
    """Regenerate the snippet tree from the examples. Returns the file count."""
    expected = _expected()
    # Drop stale snippets whose example was removed or renamed.
    for stale in _existing_snippets() - set(expected):
        stale.unlink()
    for path, content in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # Prune now-empty directories left behind by removed examples.
    if SNIPPETS_DIR.exists():
        for directory in sorted((d for d in SNIPPETS_DIR.rglob("*") if d.is_dir()), reverse=True):
            if not any(directory.iterdir()):
                directory.rmdir()
    return len(expected)


def check() -> int:
    """Verify the committed snippets match the examples. Returns an exit code."""
    expected = _expected()
    existing = _existing_snippets()
    problems: list[str] = []

    for path in sorted(existing - set(expected)):
        problems.append(f"stale snippet (no matching example): {path.relative_to(REPO_ROOT)}")

    for path, content in expected.items():
        rel = path.relative_to(REPO_ROOT)
        if not path.exists():
            problems.append(f"missing snippet: {rel}")
        elif path.read_text(encoding="utf-8") != content:
            problems.append(f"out-of-date snippet: {rel}")

    if problems:
        print("examples/ and snippets/examples/ are out of sync:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\nRun: python scripts/sync_examples.py", file=sys.stderr)
        return 1

    print(f"snippets/examples/ is in sync ({len(expected)} files).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify snippets are in sync with examples; exit non-zero on drift",
    )
    args = parser.parse_args(argv)

    if not EXAMPLES_DIR.exists():
        print(f"no examples directory at {EXAMPLES_DIR}", file=sys.stderr)
        return 1

    # A present-but-empty examples/ tree is a regression, not a valid state: with
    # zero files pyright reports 0 errors and the sync check finds nothing out of
    # date, so both would pass silently. Fail loudly in either mode instead.
    if not _iter_examples():
        print(
            f"no example files found under {EXAMPLES_DIR} — an empty examples/ tree is a regression",
            file=sys.stderr,
        )
        return 1

    if args.check:
        return check()

    count = write()
    print(f"wrote {count} snippet(s) to {SNIPPETS_DIR.relative_to(REPO_ROOT)}/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
