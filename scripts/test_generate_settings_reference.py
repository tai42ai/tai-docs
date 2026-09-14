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
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from tai42_kit.plugins import parse_plugin_spec  # noqa: E402
from tai42_kit.settings import registered_settings  # noqa: E402
from tai42_kit.settings import registry as _kit_registry  # noqa: E402

import _plugin_settings  # noqa: E402

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
    "Every registered settings group and the environment variables it reads — the core "
    "server groups, every first-party plugin's groups, and the per-named-database Postgres "
    "group — 4 entries across 2 groups (3 variables and 1 nested-group reference)."
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


def test_duplicate_group_names_get_disambiguated_headings() -> None:
    """Two registered groups sharing a class name render distinct headings — each
    tagged with its owning package — and therefore distinct anchors."""
    groups = [
        {
            "name": "TwinSettings",
            "module": "synthpkg_one.settings",
            "fields": [{"name": "a", "env_var": "ONE_A", "type": "string"}],
        },
        {
            "name": "TwinSettings",
            "module": "synthpkg_two.settings",
            "fields": [{"name": "b", "env_var": "TWO_B", "type": "string"}],
        },
    ]
    page = generate_settings_reference.render(groups)

    headings = [line for line in page.splitlines() if line.startswith("## ")]
    assert "## TwinSettings (synthpkg_one)" in headings, headings
    assert "## TwinSettings (synthpkg_two)" in headings, headings
    assert "## TwinSettings" not in headings, headings
    anchors = {generate_settings_reference._anchor(h[len("## ") :]) for h in headings}
    assert len(anchors) == len(headings), (anchors, headings)
    print("  duplicate group names: disambiguated headings and anchors")


def test_nested_group_link_follows_disambiguation() -> None:
    """A nested-group reference to a duplicated group name links to the anchor of the
    disambiguated heading owned by the referencing group's package."""
    groups = [
        {
            "name": "TwinSettings",
            "module": "synthpkg_one.settings",
            "fields": [{"name": "a", "env_var": "ONE_A", "type": "string"}],
        },
        {
            "name": "TwinSettings",
            "module": "synthpkg_two.settings",
            "fields": [{"name": "b", "env_var": "TWO_B", "type": "string"}],
        },
        {
            "name": "ParentSettings",
            "module": "synthpkg_two.settings",
            "fields": [{"name": "twin", "env_var": "", "type": "object", "nested_group": "TwinSettings"}],
        },
    ]
    page = generate_settings_reference.render(groups)

    assert "[TwinSettings (synthpkg_two)](#twinsettings-synthpkg_two)" in page, page
    print("  nested-group link: follows the referencing package's disambiguation")


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


# --- plugin discovery, import, and registration ----------------------------
#
# These exercise the shared discovery/import module the generator uses to render
# every first-party plugin's settings groups. They register real
# ``TaiBaseSettings`` subclasses into the process-global kit registry, so the
# registry is snapshotted and restored around each test: clearing it without
# restoring would empty it for the rest of the session (a re-import of an
# already-cached module never re-registers its class).


@pytest.fixture(autouse=True)
def _isolate_registry() -> Iterator[None]:
    """Snapshot/restore the kit's process-global settings registry around each test.

    It reaches ``tai42_kit.settings.registry._REGISTRY`` directly because the kit
    exposes no public snapshot/restore seam; the access runs at fixture setup, so
    a kit that renamed that attribute surfaces here as an AttributeError up front,
    not deep inside a test.
    """
    saved = dict(_kit_registry._REGISTRY)
    try:
        yield
    finally:
        _kit_registry._REGISTRY.clear()
        _kit_registry._REGISTRY.update(saved)


_SPEC_TEMPLATE = """\
spec_version: 1
namespace: tai42
name: {name}
package: tai42-{name}
version: 0.0.1
description: Synthetic plugin fixture.
license: Apache-2.0
contract: '>=11.0,<12'
categories:
  - utilities
provides:
  - kind: tool
    name: synth_tool
    module: {top_level}.deep
    description: Synthetic tool whose module defines a settings class.
"""


def _make_synthetic_plugin(tmp_path: Path, top_level: str, deep_body: str) -> _plugin_settings.PluginInfo:
    """Write an importable package with a packaged ``tai-plugin.yml`` whose
    ``provides[].module`` is a ``deep`` module NOT reachable from ``__init__``, and
    return the :class:`PluginInfo` the generator would discover for it."""
    package_dir = tmp_path / top_level
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("")
    (package_dir / "deep.py").write_text(textwrap.dedent(deep_body))
    spec_text = _SPEC_TEMPLATE.format(name=top_level.replace("_", "-"), top_level=top_level)
    (package_dir / "tai-plugin.yml").write_text(spec_text)
    sys.path.insert(0, str(tmp_path))
    spec = parse_plugin_spec(spec_text.encode(), source=str(package_dir / "tai-plugin.yml"))
    return _plugin_settings.PluginInfo(
        dist_name=f"tai42-{top_level.replace('_', '-')}",
        top_level=top_level,
        spec=spec,
        modules=(top_level, f"{top_level}.deep"),
    )


_SETTINGS_DEEP_BODY = """\
from tai42_kit.settings import TaiBaseSettings
from pydantic_settings import SettingsConfigDict


class SynthDeepSettings(TaiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="SYNTH_DEEP_")

    knob: str = "default"
"""


def test_provides_module_group_appears(tmp_path: Path) -> None:
    """A settings class defined in a ``provides[].module`` (not reachable from the
    package ``__init__``) registers once its plugin is imported."""
    info = _make_synthetic_plugin(tmp_path, "synthpkg_group", _SETTINGS_DEEP_BODY)

    before = {i.name for i in registered_settings()}
    _plugin_settings.import_plugin_settings([info])

    after = {i.name for i in registered_settings()}
    assert "SynthDeepSettings" not in before
    assert "SynthDeepSettings" in after
    print("  provides-module settings group: registered")


def test_own_package_module_not_found_aborts(tmp_path: Path) -> None:
    """A missing module INSIDE the plugin's own top-level package is a real
    breakage and aborts the run loudly."""
    body = "import synthpkg_own.absent_submodule  # noqa: F401\n"
    info = _make_synthetic_plugin(tmp_path, "synthpkg_own", body)

    with pytest.raises(ModuleNotFoundError):
        _plugin_settings.import_plugin_settings([info])
    print("  own-package ModuleNotFoundError: aborts")


def test_foreign_module_not_found_aborts(tmp_path: Path) -> None:
    """A missing module — even a foreign optional dependency — aborts the run loudly,
    naming the plugin, the module, and the missing name."""
    foreign_body = "import totally_absent_foreign_pkg  # noqa: F401\n"
    broken = _make_synthetic_plugin(tmp_path, "synthpkg_foreign", foreign_body)

    with pytest.raises(ModuleNotFoundError) as excinfo:
        _plugin_settings.import_plugin_settings([broken])

    message = str(excinfo.value)
    assert "synthpkg_foreign.deep" in message, message
    assert "totally_absent_foreign_pkg" in message, message
    print("  foreign ModuleNotFoundError: aborts")


def test_database_group_registers_once_under_the_placeholder_prefix() -> None:
    """``_register_database_group`` registers exactly one group whose fields read
    the ``TAI_DATABASE_<NAME>_PG_*`` placeholder prefix."""
    qualname = generate_settings_reference._register_database_group()

    groups = [i for i in registered_settings() if i.qualname == qualname]
    assert len(groups) == 1, groups
    env_vars = [f.env_var for f in groups[0].fields if f.env_var]
    assert env_vars, env_vars
    assert all(var.startswith("TAI_DATABASE_<NAME>_PG_") for var in env_vars), env_vars
    print("  database group: registered once under the placeholder prefix")


def main() -> int:
    print("test_generate_settings_reference:")
    test_count_rows_splits_variables_from_group_references()
    test_count_rows_rejects_a_field_with_no_env_var_and_no_nested_group()
    test_render_fallback_links_a_mapped_field_to_its_default_var()
    test_render_fallback_em_dash_for_an_unmapped_field()
    test_render_table_carries_the_fallback_and_reload_columns()
    test_duplicate_group_names_get_disambiguated_headings()
    test_nested_group_link_follows_disambiguation()
    test_render_summary_sentence_reports_each_count_in_its_own_slot()
    test_main_prints_each_count_in_its_own_slot()
    print("test_generate_settings_reference: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
