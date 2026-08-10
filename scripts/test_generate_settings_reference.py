#!/usr/bin/env python3
"""Tests for the settings-reference generator's row-count split and page summary.

Runnable from this project — the ``dev`` group and the editable sibling sources
resolve the source packages the generator imports::

    uv run pytest scripts/test_generate_settings_reference.py

Running it inside the tai42-skeleton virtualenv is a supported alternative::

    cd tai42/core/skeleton && uv run python ../../../tai-docs/scripts/test_generate_settings_reference.py

The guarantees asserted are:

* ``count_rows`` splits the rendered rows into environment variables and
  nested-group references;
* a field that is neither — no ``env_var`` and no ``nested_group`` — makes
  ``count_rows`` exit non-zero and name the offending ``Group.field`` on stderr,
  rather than falling through into neither total and being published as a row
  whose Env var cell is an em dash naming nothing;
* ``render_fallback`` links a field's ``default_namespace_var`` to the concept
  section and renders an em dash for a field with no default-namespace mapping,
  and the rendered table carries the Fallback and Reload columns (an unflagged
  field's reload class defaulting to ``hot``);
* the page's summary sentence carries each row count in its own slot, so
  swapping two of the interpolated values fails instead of rendering plausible
  prose, and each noun is singular or plural to match the count beside it;
* ``main`` prints the same counts to stdout in its own slots, with the same
  singular/plural agreement.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent

# The generator's filename is hyphenated (it is invoked as a script, never
# imported as a module), so it is loaded by path instead of by ``import``.
_SPEC = importlib.util.spec_from_file_location(
    "generate_settings_reference", SCRIPT_DIR / "generate-settings-reference.py"
)
generate_settings_reference = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = generate_settings_reference
_SPEC.loader.exec_module(generate_settings_reference)


GROUPS = [
    {
        "name": "AlphaSettings",
        "module": "pkg.alpha",
        "fields": [
            {
                "name": "url",
                "env_var": "ALPHA_URL",
                "type": "string",
                "default_namespace_var": "TAI_DEFAULT_REDIS_URL",
            },
            {"name": "beta", "env_var": "", "type": "object", "nested_group": "BetaSettings"},
        ],
    },
    {
        "name": "BetaSettings",
        "module": "pkg.beta",
        "fields": [
            {"name": "token", "env_var": "BETA_TOKEN", "type": "string"},
            {"name": "retries", "env_var": "BETA_RETRIES", "type": "integer"},
        ],
    },
]

# A field carrying neither an env var nor a nested group: unrenderable as either
# row kind, so the generator must reject it instead of emitting an empty row.
UNCLASSIFIABLE_GROUPS = [
    {
        "name": "GammaSettings",
        "module": "pkg.gamma",
        "fields": [
            {"name": "host", "env_var": "GAMMA_HOST", "type": "string"},
            {"name": "orphan", "env_var": "", "type": "string"},
        ],
    },
]

# The summary sentence ``render`` writes for GROUPS, pinned verbatim: it
# interpolates four counts that all read as plausible prose if two are swapped,
# so each has to be checked in its own slot. GROUPS holds exactly one nested-group
# reference, so the sentence also pins that each noun agrees with its own count.
EXPECTED_SUMMARY_SENTENCE = (
    "Every registered settings group and the environment variables it reads — "
    "4 entries across 2 groups (3 variables and 1 nested-group reference)."
)

# The single line ``main`` prints for GROUPS, pinned verbatim for the same reason:
# three counts that stay plausible prose when two are swapped, and a reference
# count of one that pins the singular noun ``count_noun`` picks.
EXPECTED_MAIN_STDOUT = (
    "generate-settings-reference: wrote reference/settings.mdx (2 groups, 3 variables, 1 nested-group reference)\n"
)


@contextlib.contextmanager
def _generator_wired_to(docs_root: Path) -> Iterator[None]:
    """Point the generator's module-level state at fixture groups and a throwaway tree.

    ``main`` otherwise reads the installed settings registry and writes both the
    committed page and ``docs.json``; swapping the four globals it reaches for
    keeps the run hermetic while leaving the printed path relative to the docs
    root, exactly as a real run renders it. The originals are always restored.
    """
    module = generate_settings_reference
    names = ("load_groups", "update_nav", "DOCS_ROOT", "OUT_FILE")
    saved = {name: getattr(module, name) for name in names}
    module.load_groups = lambda: GROUPS
    module.update_nav = lambda: None
    module.DOCS_ROOT = docs_root
    module.OUT_FILE = docs_root / "reference" / "settings.mdx"
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(module, name, value)


def test_count_rows_splits_variables_from_group_references() -> None:
    """Three env-var fields and one nested-group reference."""
    variables, references = generate_settings_reference.count_rows(GROUPS)

    assert (variables, references) == (3, 1)


def test_count_rows_rejects_a_field_with_no_env_var_and_no_nested_group() -> None:
    """An unclassifiable field aborts the run and is named on stderr."""
    stderr = io.StringIO()
    with pytest.raises(SystemExit) as excinfo, contextlib.redirect_stderr(stderr):
        generate_settings_reference.count_rows(UNCLASSIFIABLE_GROUPS)

    assert excinfo.value.code == 1
    message = stderr.getvalue()
    assert "generate-settings-reference:" in message
    assert "GammaSettings.orphan" in message
    # The classifiable field in the same group is not an offender.
    assert "GammaSettings.host" not in message


def test_render_fallback_links_a_mapped_field_to_its_default_var() -> None:
    """A field with a ``default_namespace_var`` renders it as a linked code cell."""
    cell = generate_settings_reference.render_fallback({"default_namespace_var": "TAI_DEFAULT_REDIS_URL"})

    assert cell == ("[`TAI_DEFAULT_REDIS_URL`](/concepts/config-and-secrets#default-connection-namespace)")


def test_render_fallback_em_dash_for_an_unmapped_field() -> None:
    """A field with no default-namespace mapping renders an em dash, not a link."""
    assert generate_settings_reference.render_fallback({}) == "—"
    assert generate_settings_reference.render_fallback({"default_namespace_var": None}) == "—"


def test_render_table_carries_the_fallback_and_reload_columns() -> None:
    """The rendered table header carries the Fallback and Reload columns, links a
    mapped field, and defaults an unflagged field's Reload cell to ``hot``."""
    page = generate_settings_reference.render(GROUPS)

    assert "| Env var | Type | Default | Fallback | Required | Reload | Description |" in page
    assert "|---|---|---|---|---|---|---|" in page
    # Pin the whole row, not just that the link appears somewhere: this catches a
    # cell landing in the wrong column (e.g. Fallback and Required swapped).
    assert (
        "| `ALPHA_URL` | `string` | — | "
        "[`TAI_DEFAULT_REDIS_URL`](/concepts/config-and-secrets#default-connection-namespace) | "
        "Optional | `hot` | — |"
    ) in page


def test_render_summary_sentence_reports_each_count_in_its_own_slot() -> None:
    """The rendered page states 4 entries, 2 groups, 3 variables, 1 reference — singular."""
    page = generate_settings_reference.render(GROUPS)

    assert EXPECTED_SUMMARY_SENTENCE in page


def test_main_prints_each_count_in_its_own_slot() -> None:
    """main's stdout line states 2 groups, 3 variables, 1 reference — singular."""
    stdout = io.StringIO()
    with (
        tempfile.TemporaryDirectory() as docs_root,
        _generator_wired_to(Path(docs_root)),
        contextlib.redirect_stdout(stdout),
    ):
        exit_code = generate_settings_reference.main()

    assert exit_code == 0
    assert stdout.getvalue() == EXPECTED_MAIN_STDOUT


def main() -> int:
    print("test_generate_settings_reference:")
    test_count_rows_splits_variables_from_group_references()
    test_count_rows_rejects_a_field_with_no_env_var_and_no_nested_group()
    test_render_fallback_links_a_mapped_field_to_its_default_var()
    test_render_fallback_em_dash_for_an_unmapped_field()
    test_render_table_carries_the_fallback_and_reload_columns()
    test_render_summary_sentence_reports_each_count_in_its_own_slot()
    test_main_prints_each_count_in_its_own_slot()
    print("test_generate_settings_reference: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
