"""Execute the CLI / curl / YAML operator examples and assert their outcomes.

The Python examples are single-sourced and type-checked (``sync_examples.py`` +
pyright), but a ``tai …`` command, a ``curl``, or a manifest YAML that only ever
renders as prose can rot silently — a route rename, a flag change, or a status
change never touches the page. This harness closes that gap: it RUNS every
executable example and asserts a declared outcome, so a feature change that
breaks an example fails the build and forces the doc to be updated.

Each executable example (``examples/**/*.sh`` and ``examples/**/*.yaml``) carries
a leading ``#|`` metadata block declaring its expectation (see the authoring
contract). The body — everything after the block — is exactly what renders in the
docs and exactly what runs here, so the two can never diverge.

Shell examples (``.sh``, i.e. ``tai`` or ``curl`` snippets)::

    #| fixture: ac_app                 # live app to boot first (default: none)
    #| expect_exit: 0                  # required process exit code (default: 0)
    #| expect_stdout_contains: 200     # substring the stdout must contain (optional)
    curl -sS -o /dev/null -w '%{http_code}\\n' -H "X-Api-Key: $TAI_API_KEY" "$TAI_BASE_URL/guarded"

The named fixture (``example_fixtures.FIXTURES``) is booted once and exports the
environment variables the body references (``$TAI_BASE_URL``, ``$TAI_API_KEY``…).

YAML examples (``.yaml`` / ``.yml``) validate against a landed contract model::

    #| validate: preset                # contract model to validate against
    base_tool: echo_tool

A ``validate:`` example must load AND validate; a malformed or schema-invalid
document fails the harness. An executable example with NO ``#|`` block is a
regression (an unasserted example) and fails loudly.

Usage::

    cd tai42/core/skeleton && uv run python ../../../tai-docs/scripts/run_examples.py
    cd tai42/core/skeleton && uv run python ../../../tai-docs/scripts/run_examples.py --list
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sync_examples  # noqa: E402
from example_fixtures import FIXTURES  # noqa: E402

# A ``tai`` command renders its help through rich/typer, which highlights each
# option — including splitting the leading ``--`` of a flag into its own styled
# span — when color is on (a runner exporting ``FORCE_COLOR`` forces color even
# though stdout is a pipe). That styling injects ANSI escapes mid-token, so
# ``"--input" in stdout`` on the raw bytes wrongly fails. The assertion is about
# the VISIBLE CLI surface, not terminal styling, so the captured output is
# stripped of ANSI escapes before it is matched. Matches CSI sequences (color +
# cursor) and the other single-character escapes rich can emit.
_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# Only these kinds are EXECUTED here; Python examples are covered by pyright.
EXEC_SUFFIXES = (".sh", ".yaml", ".yml")

# The metadata keys each kind understands. Any other ``#|`` key is a typo (say
# ``expct_exit`` or ``expect_stdout_contain``) whose intended assertion would
# otherwise be SILENTLY dropped — the example would falsely PASS. ``discover()``
# validates every key against these sets and raises, mirroring the loud failure it
# already gives an unasserted example. Shell examples run a fixture and assert on
# the process; YAML examples are pure contract validation (no fixture, no process).
SHELL_META_KEYS = frozenset({"fixture", "expect_exit", "expect_stdout_contains"})
YAML_META_KEYS = frozenset({"validate"})

# ``#| validate: <name>`` -> the landed contract model the YAML must satisfy. The
# import is lazy (inside the validator) so ``--list`` and the shell path never
# require the contract to be importable.
YAML_MODELS: dict[str, Callable[[dict], object]] = {}


def _load_yaml_models() -> None:
    """Populate ``YAML_MODELS`` from the landed contract, once and lazily."""
    if YAML_MODELS:
        return
    from tai42_contract.interactions.models import MediaItem
    from tai42_contract.manifest import Manifest
    from tai42_contract.presets import PresetBody

    YAML_MODELS["preset"] = lambda data: PresetBody(**data)
    YAML_MODELS["manifest"] = lambda data: Manifest(**data)
    # ``media`` validates the display-only media list a question attaches: each
    # entry under the ``media`` key must be a valid ``MediaItem`` (its kind, url
    # form, and caption caps enforced by the contract).
    YAML_MODELS["media"] = lambda data: [MediaItem(**item) for item in data["media"]]


@dataclass
class Example:
    path: Path
    suffix: str
    meta: dict[str, str]
    body: str

    @property
    def rel(self) -> str:
        return self.path.relative_to(sync_examples.EXAMPLES_DIR).as_posix()

    @property
    def fixture(self) -> str:
        return self.meta.get("fixture", "none")


@dataclass
class Result:
    example: Example
    ok: bool
    detail: str


@dataclass
class _Run:
    passed: list[Result] = field(default_factory=list)
    failed: list[Result] = field(default_factory=list)


def discover() -> list[Example]:
    """Every executable example, parsed. Fails loudly on an unasserted example."""
    examples: list[Example] = []
    for path in sync_examples._iter_examples():
        if path.suffix not in EXEC_SUFFIXES:
            continue
        meta, body = sync_examples.split_example(path.read_text(encoding="utf-8"))
        if not meta:
            raise ValueError(
                f"executable example {path} has no '#|' metadata block — every .sh/.yaml example "
                f"must declare its expected outcome (see the example harness contract)"
            )
        allowed = SHELL_META_KEYS if path.suffix == ".sh" else YAML_META_KEYS
        unknown = set(meta) - allowed
        if unknown:
            raise ValueError(
                f"executable example {path} declares unrecognized '#|' metadata key(s) "
                f"{sorted(unknown)!r} — a typo here silently drops the intended assertion. "
                f"Allowed for {path.suffix} examples: {sorted(allowed)}"
            )
        empty = sorted(key for key in meta if not meta[key])
        if empty:
            raise ValueError(
                f"executable example {path} has empty '#|' metadata value(s) for {empty!r} — an empty "
                f"value asserts nothing (e.g. an empty expect_stdout_contains needle always 'passes')"
            )
        examples.append(Example(path=path, suffix=path.suffix, meta=meta, body=body))
    return examples


def _run_shell(example: Example, env: dict[str, str]) -> Result:
    expect_exit = int(example.meta.get("expect_exit", "0"))
    needle = example.meta.get("expect_stdout_contains")

    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as handle:
        handle.write(example.body)
        script = handle.name
    try:
        proc = subprocess.run(
            ["bash", script],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
    finally:
        os.unlink(script)

    # Compare against the VISIBLE surface: a color-forcing runner makes rich/typer
    # emit ANSI escapes that split a flag's ``--`` across styled spans, so match on
    # the escape-stripped output rather than the raw bytes.
    stdout = _strip_ansi(proc.stdout)

    problems: list[str] = []
    if proc.returncode != expect_exit:
        problems.append(f"exit {proc.returncode} != expected {expect_exit}")
    if needle is not None and needle not in stdout:
        problems.append(f"stdout missing {needle!r}")

    if problems:
        detail = "; ".join(problems)
        tail = (stdout or _strip_ansi(proc.stderr) or "").strip().splitlines()[-3:]
        if tail:
            detail += " | output: " + " / ".join(tail)
        return Result(example, ok=False, detail=detail)
    got = stdout.strip().splitlines()
    return Result(
        example,
        ok=True,
        detail=f"exit {proc.returncode}"
        + (f", stdout~{needle!r}" if needle else "")
        + (f" ({got[-1]})" if got else ""),
    )


def _run_yaml(example: Example) -> Result:
    target = example.meta.get("validate")
    try:
        data = yaml.safe_load(example.body)
    except yaml.YAMLError as exc:
        return Result(example, ok=False, detail=f"not valid YAML: {exc}")
    if not isinstance(data, dict):
        return Result(example, ok=False, detail=f"expected a YAML mapping, got {type(data).__name__}")
    if target is None:
        return Result(example, ok=False, detail="missing '#| validate: <model>' — a YAML example must be validated")

    _load_yaml_models()
    model = YAML_MODELS.get(target)
    if model is None:
        return Result(example, ok=False, detail=f"unknown validate target {target!r} (known: {sorted(YAML_MODELS)})")
    try:
        model(data)
    except Exception as exc:  # any validation error is a failure
        return Result(example, ok=False, detail=f"failed {target} validation: {exc}")
    return Result(example, ok=True, detail=f"validated against {target}")


def run(examples: list[Example]) -> _Run:
    """Boot each referenced fixture once and run its examples inside it."""
    outcome = _Run()
    by_fixture: dict[str, list[Example]] = {}
    for example in examples:
        by_fixture.setdefault(example.fixture, []).append(example)

    for fixture_name, group in sorted(by_fixture.items()):
        factory = FIXTURES.get(fixture_name)
        if factory is None:
            for example in group:
                outcome.failed.append(
                    Result(example, ok=False, detail=f"unknown fixture {fixture_name!r} (known: {sorted(FIXTURES)})")
                )
            continue
        with factory() as fixture_env:  # type: ignore[operator]
            env = {**os.environ, **fixture_env}
            for example in group:
                result = _run_shell(example, env) if example.suffix == ".sh" else _run_yaml(example)
                (outcome.passed if result.ok else outcome.failed).append(result)
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list discovered executable examples and exit")
    args = parser.parse_args(argv)

    examples = discover()
    if not examples:
        print(
            "no executable examples found under examples/ (*.sh, *.yaml) — the executable-example "
            "harness must exercise at least one example",
            file=sys.stderr,
        )
        return 1

    if args.list:
        for example in examples:
            print(f"{example.rel}  [fixture={example.fixture}] {example.meta}")
        return 0

    outcome = run(examples)
    for result in outcome.passed:
        print(f"  PASS  {result.example.rel}  ({result.detail})")
    for result in outcome.failed:
        print(f"  FAIL  {result.example.rel}  ({result.detail})", file=sys.stderr)

    total = len(outcome.passed) + len(outcome.failed)
    if outcome.failed:
        print(f"\nrun_examples: {len(outcome.failed)}/{total} executable example(s) FAILED.", file=sys.stderr)
        return 1
    print(f"\nrun_examples: all {total} executable example(s) passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
