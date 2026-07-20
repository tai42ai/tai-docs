#!/usr/bin/env python3
"""Freshness gate: fail if the committed reference has drifted from the source.

Re-runs every reference generator and compares their output against the files
committed in this repository. If a merged code change altered the HTTP API, CLI,
Python SDK, ecosystem catalog, the settings reference, or the standard-toolbox
table without the reference being regenerated, the committed files differ from a
fresh run and this exits non-zero -- the standard "generated files are checked in
AND verified fresh in CI" pattern.

The check is non-mutating. It snapshots the committed generated files, runs the
generators (which write in place), diffs the fresh output against the snapshot,
then restores the snapshot -- so a drift run reports the drift without altering
the working tree. In CI the drift is what triggers the automated regeneration
PR; the deployed site always builds from the committed files.

Run it where the source packages resolve (the tai42-skeleton virtualenv)::

    cd tai-skeleton && uv run python ../tai-docs/scripts/check_drift.py
"""

from __future__ import annotations

import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent

# The generators (in run order) and every path they own. `docs.json` is shared:
# each generator rewrites only its own Reference nav group, so it is compared
# once after every generator has run.
GENERATORS = [
    "gen_openapi.py",
    "gen_cli.py",
    "gen_sdk.py",
    "gen_studio_sdk.py",
    "gen_catalog.py",
    "generate-settings-reference.py",
    "gen_toolbox_table.py",
]

GENERATED_PATHS = [
    "openapi.json",
    "docs.json",
    "reference/cli",
    "reference/python-sdk",
    "reference/studio-sdk",
    "reference/catalog",
    "reference/settings.mdx",
    "guides/standard-toolbox.mdx",
]

# The example-snippet sync is owned by a separate generator (sync_examples.py).
# check_drift mirrors CI by invoking its --check mode as one step, when present.
SYNC_EXAMPLES = SCRIPT_DIR / "sync_examples.py"


def _snapshot(dest: Path) -> None:
    for rel in GENERATED_PATHS:
        src = DOCS_ROOT / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)


def _restore(snapshot: Path) -> None:
    for rel in GENERATED_PATHS:
        src = snapshot / rel
        target = DOCS_ROOT / rel
        if src.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)


def _diff_paths(snapshot: Path) -> list[str]:
    """Return the list of generated files that changed after regeneration."""
    changed: list[str] = []
    for rel in GENERATED_PATHS:
        old = snapshot / rel
        new = DOCS_ROOT / rel
        if old.is_dir():
            cmp = filecmp.dircmp(old, new)
            changed += _walk_dircmp(cmp, Path(rel))
        elif not filecmp.cmp(old, new, shallow=False):
            changed.append(rel)
    return sorted(changed)


def _walk_dircmp(cmp: filecmp.dircmp, prefix: Path) -> list[str]:
    changed = [str(prefix / n) for n in cmp.diff_files]
    changed += [str(prefix / n) + " (only in fresh output)" for n in cmp.right_only]
    changed += [str(prefix / n) + " (only in committed reference)" for n in cmp.left_only]
    for name, sub in cmp.subdirs.items():
        changed += _walk_dircmp(sub, prefix / name)
    return changed


def _run_generators() -> None:
    for gen in GENERATORS:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / gen)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"{gen} exited {proc.returncode}:\n{proc.stderr.strip() or proc.stdout.strip()}")


def _check_examples_sync() -> int:
    """Run ``sync_examples.py --check`` when that generator is present.

    The example snippets are owned by a separate generator; check_drift mirrors
    CI by running its ``--check`` mode as one step. When the script is not yet
    present the check is skipped with a loud NOTE (CI runs it unconditionally, so
    the gate is never silently weakened there)."""
    if not SYNC_EXAMPLES.is_file():
        print(
            "check_drift: NOTE -- scripts/sync_examples.py not present; skipping the "
            "example-snippet sync check (owned separately; CI runs it unconditionally)."
        )
        return 0
    proc = subprocess.run(
        [sys.executable, str(SYNC_EXAMPLES), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print("check_drift: example snippets are OUT OF SYNC with examples/:", file=sys.stderr)
        print(proc.stderr.strip() or proc.stdout.strip(), file=sys.stderr)
        return 1
    print("check_drift: example-snippet sync OK.")
    return 0


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "committed"
        _snapshot(snapshot)
        try:
            _run_generators()
        except RuntimeError as exc:
            _restore(snapshot)
            print(f"check_drift: a generator FAILED -- {exc}", file=sys.stderr)
            return 1
        changed = _diff_paths(snapshot)
        _restore(snapshot)

    if changed:
        print("check_drift: DRIFT -- the committed reference is stale.", file=sys.stderr)
        print("The following generated files differ from a fresh run:", file=sys.stderr)
        for path in changed:
            print(f"  - {path}", file=sys.stderr)
        print(
            "\nRegenerate the reference (run every generator) and commit the "
            "result. In CI this drift opens the automated regeneration PR.",
            file=sys.stderr,
        )
        return 1

    # Reference is fresh; mirror CI's example-snippet sync check as one step.
    sync_rc = _check_examples_sync()
    if sync_rc != 0:
        return sync_rc

    print(f"check_drift: OK -- all {len(GENERATED_PATHS)} generated paths are fresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
