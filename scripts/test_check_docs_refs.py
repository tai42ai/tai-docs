#!/usr/bin/env python3
"""Tests for the hand-written-reference drift-check.

Runnable from this project offline -- the valid-distribution set is read from the
committed ``plugins/_registry.json`` snapshot::

    uv run pytest scripts/test_check_docs_refs.py

Guarantees asserted:

1. A doc naming a real distribution / real repo passes.
2. A fabricated ``tai42-bogus`` distribution fails, naming its ``file:line``.
3. A documented ALWAYS_PUBLIC value that differs from the compose default fails.
4. A bundled-plugin-env value that differs from the dist preset fails, and the
   block must name exactly the tracked bundled-plugin variables; operator-fill
   placeholders (all-zero digest, empty value) match by convention, while a name
   drift or a real value behind a placeholder is still caught.
5. The current committed tree passes (no reference drift).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_docs_refs  # noqa: E402
from _plugin_settings import BundledEnvNamespaces  # noqa: E402


def _dist_map() -> dict[str, str]:
    return check_docs_refs.load_distribution_map()


# --- distribution names ----------------------------------------------------


def test_real_distribution_passes() -> None:
    """A doc naming real distributions produces no problems."""
    dist_map = _dist_map()
    docs = [("fake/install.mdx", "Run `pip install tai42-skeleton` and `uv sync --extra toolbox` for tai42-toolbox.")]
    problems = check_docs_refs.check_distribution_names(docs, set(dist_map))
    assert problems == [], problems
    print("  real distribution names: no problems")


def test_bogus_distribution_fails() -> None:
    """A fabricated tai42-bogus is flagged with its file:line."""
    dist_map = _dist_map()
    docs = [("fake/install.mdx", "line one\nRun `pip install tai42-bogus` here.\n")]
    problems = check_docs_refs.check_distribution_names(docs, set(dist_map))
    assert len(problems) == 1, problems
    assert problems[0].startswith("fake/install.mdx:2:"), problems[0]
    assert "tai42-bogus" in problems[0]
    print("  bogus distribution: flagged at file:line")


def test_logo_asset_not_mistaken_for_distribution() -> None:
    """The `/tai42-logo-icon.png` asset path is not read as a distribution name."""
    dist_map = _dist_map()
    docs = [("fake/deploy.mdx", 'PREFIXES=\'["/tai42-logo-icon.png", "/"]\'')]
    problems = check_docs_refs.check_distribution_names(docs, set(dist_map))
    assert problems == [], problems
    print("  logo asset path: not mistaken for a distribution")


def test_vendor_annotation_not_mistaken_for_distribution() -> None:
    """`x-tai42-expression` is a JSON-Schema vendor annotation, not a distribution.

    The token is anchored at the start of its hyphenated word, so a longer
    identifier that merely ENDS in a distribution-shaped suffix never matches."""
    dist_map = _dist_map()
    docs = [("fake/api.mdx", "The field carries an `x-tai42-expression` annotation.")]
    problems = check_docs_refs.check_distribution_names(docs, set(dist_map))
    assert problems == [], problems
    print("  x-tai42-expression annotation: not mistaken for a distribution")


def test_slash_prefixed_bogus_distribution_flagged() -> None:
    """A slash-prefixed distribution token (e.g. inside a URL) is still detected —
    the exclusion is scoped to image assets, not to any leading slash."""
    dist_map = _dist_map()
    docs = [("fake/install.mdx", "See https://pypi.org/project/tai42-bogus for the package.")]
    problems = check_docs_refs.check_distribution_names(docs, set(dist_map))
    assert len(problems) == 1, problems
    assert "tai42-bogus" in problems[0], problems[0]
    print("  slash-prefixed bogus distribution: flagged")


# --- repo URLs -------------------------------------------------------------


def test_monorepo_url_passes() -> None:
    """The bare monorepo URL is genuinely recognized as the real repo."""
    docs = [("fake/x.mdx", "git clone https://github.com/tai42ai/tai42")]
    problems, notes = check_docs_refs.check_repo_urls(docs, workspace_root=Path("/nonexistent"))
    assert problems == [], problems
    assert notes == [], notes
    print("  monorepo root URL: recognized, no problems")


def test_monorepo_member_path_validated(tmp_path: Path) -> None:
    """With the monorepo checkout present, a member path is checked: a real one
    passes and a typo fails CLOSED with its file:line."""
    (tmp_path / "tai42" / "plugins" / "toolbox").mkdir(parents=True)

    good = [("fake/x.mdx", "See https://github.com/tai42ai/tai42/tree/main/plugins/toolbox")]
    problems, notes = check_docs_refs.check_repo_urls(good, workspace_root=tmp_path)
    assert problems == [], problems
    assert notes == [], notes

    bad = [("fake/x.mdx", "line one\nSee https://github.com/tai42ai/tai42/tree/main/plugins/toolbx\n")]
    problems, _ = check_docs_refs.check_repo_urls(bad, workspace_root=tmp_path)
    assert len(problems) == 1, problems
    assert problems[0].startswith("fake/x.mdx:2:"), problems[0]
    assert "plugins/toolbx" in problems[0]
    print("  monorepo member path: verified against checkout, typo flagged")


def test_monorepo_member_path_offline_notes() -> None:
    """Offline (no monorepo checkout) a member path notes, never fails —
    the checkout-present run verifies it."""
    docs = [("fake/x.mdx", "https://github.com/tai42ai/tai42/tree/main/core/skeleton")]
    problems, notes = check_docs_refs.check_repo_urls(docs, workspace_root=Path("/nonexistent"))
    assert problems == [], problems
    assert len(notes) == 1, notes
    assert "not present offline" in notes[0], notes
    print("  monorepo member path offline: noted, no failure")


def test_infra_repo_url_passes() -> None:
    """A known non-package repo (tai-distribution) resolves via the infra allowlist."""
    docs = [("fake/x.mdx", "See https://github.com/tai42ai/tai-distribution for the compose bundle.")]
    problems, notes = check_docs_refs.check_repo_urls(docs, workspace_root=Path("/nonexistent"))
    assert problems == [], problems
    assert notes == [], notes
    print("  infra repo URL: recognized via allowlist")


def test_bogus_repo_url_fails() -> None:
    """A typo'd/renamed standalone repo URL fails CLOSED with its file:line —
    neither a package repo, a known non-package repo, nor a present sibling."""
    docs = [("fake/x.mdx", "line one\ngit clone https://github.com/tai42ai/tai-skeltn\n")]
    problems, _ = check_docs_refs.check_repo_urls(docs, workspace_root=Path("/nonexistent"))
    assert len(problems) == 1, problems
    assert problems[0].startswith("fake/x.mdx:2:"), problems[0]
    assert "tai-skeltn" in problems[0]
    print("  bogus repo URL: flagged at file:line")


# --- ALWAYS_PUBLIC ---------------------------------------------------------


def test_mismatched_always_public_fails() -> None:
    """A documented ALWAYS_PUBLIC value that differs from the default fails."""
    default = ["/api/login", "/assets", "/"]
    docs = [("fake/deploy.mdx", "x\nexport ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES='[\"/api/login\"]'\n")]
    problems = check_docs_refs.compare_always_public(docs, default)
    assert len(problems) == 1, problems
    assert problems[0].startswith("fake/deploy.mdx:2:"), problems[0]
    print("  mismatched ALWAYS_PUBLIC: flagged at file:line")


def test_matching_always_public_passes() -> None:
    """A documented ALWAYS_PUBLIC value equal to the default passes."""
    default = ["/api/login", "/assets", "/"]
    value = 'export ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES=\'["/api/login", "/assets", "/"]\''
    docs = [("fake/deploy.mdx", value)]
    problems = check_docs_refs.compare_always_public(docs, default)
    assert problems == [], problems
    print("  matching ALWAYS_PUBLIC: no problems")


def test_double_quoted_always_public_verified() -> None:
    """A documented value in the double-quoted / JSON-array form (not the shell
    single-quoted form) is still verified: a mismatch is flagged and a match passes."""
    default = ["/api/login", "/assets", "/"]

    mismatch = 'ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES="["/api/login"]"'
    problems = check_docs_refs.compare_always_public([("fake/deploy.mdx", mismatch)], default)
    assert len(problems) == 1, problems
    assert problems[0].startswith("fake/deploy.mdx:1:"), problems[0]

    match = 'ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES="["/api/login", "/assets", "/"]"'
    problems = check_docs_refs.compare_always_public([("fake/deploy.mdx", match)], default)
    assert problems == [], problems
    print("  double-quoted ALWAYS_PUBLIC: mismatch flagged, match passes")


def test_compose_regex_extracts_default() -> None:
    """The compose-side ``${VAR:-[...]}`` extraction regex pulls the JSON default —
    the source-of-truth read the whole ALWAYS_PUBLIC comparison hinges on."""
    import json

    line = (
        "  ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES: "
        '\'${ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES:-["/api/login", "/assets", "/"]}\''
    )
    m = check_docs_refs._ALWAYS_PUBLIC_COMPOSE_RE.search(line)
    assert m is not None, "compose regex failed to match the ${VAR:-[...]} default"
    assert json.loads(m.group(1)) == ["/api/login", "/assets", "/"]
    print("  compose ALWAYS_PUBLIC regex: extracts the JSON default")


# --- core roster -----------------------------------------------------------


def _roster_doc(tokens: str) -> str:
    start = check_docs_refs.ROSTER_MARKER_START
    end = check_docs_refs.ROSTER_MARKER_END
    return f"line one\n{{/* {start} */}}\n{tokens}\n{{/* {end} */}}\n"


def test_requirement_names_strips_extras_and_pins() -> None:
    """Package names parse out of a requirements file, dropping extras and versions."""
    text = "# comment\ntai42-skeleton[toolbox,files]==0.3.1\ntai42-backend-arq==0.3.1\n\n"
    names = check_docs_refs._requirement_names(text)
    assert names == {"tai42-skeleton", "tai42-backend-arq"}, names
    print("  requirement names: extras and version pins stripped")


def test_matching_roster_passes(tmp_path: Path) -> None:
    """A roster block naming exactly the pinned set produces no problems."""
    (tmp_path / "tai-distribution" / "docker").mkdir(parents=True)
    (tmp_path / "tai-distribution" / "docker" / "pypi-requirements.txt").write_text(
        "tai42-skeleton[toolbox,files]==0.3.1\ntai42-backend-arq==0.3.1\n"
    )
    docs = [("self-hosted/index.mdx", _roster_doc("`tai42-skeleton` and `tai42-backend-arq`"))]
    problems, _ = check_docs_refs.check_core_roster(docs, workspace_root=tmp_path)
    assert problems == [], problems
    print("  matching roster: no problems")


def test_roster_missing_and_extra_flagged(tmp_path: Path) -> None:
    """A roster that drops a bundled package and adds a non-bundled one flags both."""
    (tmp_path / "tai-distribution" / "docker").mkdir(parents=True)
    (tmp_path / "tai-distribution" / "docker" / "pypi-requirements.txt").write_text(
        "tai42-skeleton==0.3.1\ntai42-backend-arq==0.3.1\n"
    )
    docs = [("self-hosted/index.mdx", _roster_doc("`tai42-skeleton` and `tai42-channel-slack`"))]
    problems, _ = check_docs_refs.check_core_roster(docs, workspace_root=tmp_path)
    assert len(problems) == 2, problems
    assert any("tai42-backend-arq" in p and "missing" in p for p in problems), problems
    assert any("tai42-channel-slack" in p and "does NOT bundle" in p for p in problems), problems
    print("  roster drift: missing and extra packages both flagged")


def test_absent_roster_block_fails(tmp_path: Path) -> None:
    """A present requirements file with no roster block in the docs is drift."""
    (tmp_path / "tai-distribution" / "docker").mkdir(parents=True)
    (tmp_path / "tai-distribution" / "docker" / "pypi-requirements.txt").write_text("tai42-skeleton==0.3.1\n")
    docs = [("self-hosted/index.mdx", "no markers here\n")]
    problems, _ = check_docs_refs.check_core_roster(docs, workspace_root=tmp_path)
    assert len(problems) == 1, problems
    assert "no core-roster block" in problems[0], problems[0]
    print("  absent roster block: flagged")


def test_absent_requirements_notes_not_fails() -> None:
    """Offline (no tai-distribution checkout) the roster check notes, never fails."""
    docs = [("self-hosted/index.mdx", _roster_doc("`tai42-skeleton`"))]
    problems, notes = check_docs_refs.check_core_roster(docs, workspace_root=Path("/nonexistent"))
    assert problems == [], problems
    assert len(notes) == 1, notes
    assert "not present offline" in notes[0], notes
    print("  absent requirements: offline note, no failure")


# --- bundled-plugin env presets --------------------------------------------


def _bundled_env_doc(rows: list[tuple[str, str, str]]) -> str:
    start = check_docs_refs.BUNDLED_PLUGIN_ENV_MARKER_START
    end = check_docs_refs.BUNDLED_PLUGIN_ENV_MARKER_END
    body = "\n".join(f"| `{pkg}` | `{var}` | `{value}` |" for pkg, var, value in rows)
    return f"line one\n{{/* {start} */}}\n| a | b | c |\n{body}\n{{/* {end} */}}\n"


def _write_dist_env(tmp_path: Path, compose: str, env_example: str) -> None:
    compose_dir = tmp_path / "tai-distribution" / "compose"
    compose_dir.mkdir(parents=True)
    (compose_dir / "docker-compose.yml").write_text(compose)
    (compose_dir / ".env.example").write_text(env_example)


_FIXTURE_COMPOSE = (
    "x-tai-app-env: &tai-app-env\n"
    "  ARQ_REDIS_URL: redis://redis:6379/0\n"
    '  SANDBOX_DOCKER_HOST: "${SANDBOX_DOCKER_HOST:-}"\n'
    '  SANDBOX_LOCAL_ROOT: "${SANDBOX_LOCAL_ROOT:-}"\n'
    "services:\n"
    "  serve:\n"
    "    image: x\n"
    "    environment:\n"
    "      <<: *tai-app-env\n"
    '      SANDBOX_DOCKER_READINESS_PROBE_ENABLED: "1"\n'
)
_ZERO_DIGEST = "sha256:" + "0" * 64
_FIXTURE_ENV = (
    "# comment\n"
    "SANDBOX_DOCKER_HOST=tcp://sandbox-engine:2376\n"
    "SANDBOX_LOCAL_ROOT=/var/lib/tai-sandbox-local\n"
    f"TAI_AGENTS_CLAUDE_SESSION_IMAGE=docker.io/tai42/tai-sandbox-claude-code@{_ZERO_DIGEST}\n"
    f"TAI_AGENTS_LANGCHAIN_DEEP_SESSION_IMAGE=docker.io/tai42/tai-sandbox-exec@{_ZERO_DIGEST}\n"
    "TAI_AGENTS_CLAUDE_API_KEY=\n"
)

# Synthetic bundled-plugin namespaces (the registry prefixes the real derivation
# reads) injected into the check so these tests never touch the live registry.
_FIXTURE_NAMESPACES = BundledEnvNamespaces(
    prefixes=frozenset({"ARQ_", "SANDBOX_DOCKER_", "SANDBOX_LOCAL_", "TAI_AGENTS_"}),
    env_vars=frozenset(),
)

_MATCHING_ROWS = [
    ("tai42-backend-arq", "ARQ_REDIS_URL", "redis://redis:6379/0"),
    ("tai42-sandbox-docker", "SANDBOX_DOCKER_HOST", "tcp://sandbox-engine:2376"),
    ("tai42-sandbox-docker", "SANDBOX_DOCKER_READINESS_PROBE_ENABLED", "1"),
    ("tai42-sandbox-local", "SANDBOX_LOCAL_ROOT", "/var/lib/tai-sandbox-local"),
    ("tai42-agents", "TAI_AGENTS_CLAUDE_SESSION_IMAGE", "docker.io/tai42/tai-sandbox-claude-code@<digest>"),
    ("tai42-agents", "TAI_AGENTS_LANGCHAIN_DEEP_SESSION_IMAGE", "docker.io/tai42/tai-sandbox-exec@<digest>"),
    ("tai42-agents", "TAI_AGENTS_CLAUDE_API_KEY", "<set by operator>"),
]


def _check(docs: list[tuple[str, str]], tmp_path: Path) -> tuple[list[str], list[str]]:
    """Run the bundled-plugin-env check with the synthetic namespaces injected."""
    return check_docs_refs.check_bundled_plugin_env(docs, workspace_root=tmp_path, namespaces=_FIXTURE_NAMESPACES)


def test_compose_env_presets_merges_anchor_and_services() -> None:
    """The preset reader resolves a literal, a ``${VAR:-default}``, and a
    ``${VAR:?msg}`` (required, no default) to ``None``, and merges each service's
    own ``environment`` block over the shared anchor."""
    presets = check_docs_refs._compose_env_presets(
        _FIXTURE_COMPOSE.replace(
            "  SANDBOX_LOCAL_ROOT:", '  POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:?set it}"\n  SANDBOX_LOCAL_ROOT:'
        )
    )
    assert presets["ARQ_REDIS_URL"] == "redis://redis:6379/0"
    assert presets["SANDBOX_DOCKER_HOST"] == ""
    assert presets["POSTGRES_PASSWORD"] is None
    # From serve's own environment block, merged over the anchor.
    assert presets["SANDBOX_DOCKER_READINESS_PROBE_ENABLED"] == "1"
    print("  compose env presets: anchor + service env merged, substitutions resolved")


def test_compose_env_presets_conflicting_service_values_raise() -> None:
    """A key two services set to disagreeing values is a source ambiguity and raises."""
    compose = (
        "x-tai-app-env: &tai-app-env\n"
        "  ARQ_REDIS_URL: redis://redis:6379/0\n"
        "services:\n"
        "  serve:\n"
        "    environment:\n"
        "      <<: *tai-app-env\n"
        '      KNOB: "1"\n'
        "  backend:\n"
        "    environment:\n"
        "      <<: *tai-app-env\n"
        '      KNOB: "2"\n'
    )
    with pytest.raises(RuntimeError, match="conflicting values"):
        check_docs_refs._compose_env_presets(compose)
    print("  compose env presets: conflicting service values raise")


def test_env_example_parse_skips_comments() -> None:
    """The env-template parse records uncommented ``KEY=value`` and skips comments."""
    values = check_docs_refs._parse_env_example("# skip me\nSANDBOX_LOCAL_ROOT=/var/lib/tai-sandbox-local\nEMPTY=\n")
    assert values == {"SANDBOX_LOCAL_ROOT": "/var/lib/tai-sandbox-local", "EMPTY": ""}
    print("  env template: comments skipped, empty value kept")


def test_bundled_plugin_env_matching_passes(tmp_path: Path) -> None:
    """A block matching the dist presets (env-template value winning over the anchor
    default, plus the readiness probe from a service block) produces no problems."""
    _write_dist_env(tmp_path, _FIXTURE_COMPOSE, _FIXTURE_ENV)
    docs = [("self-hosted/index.mdx", _bundled_env_doc(_MATCHING_ROWS))]
    problems, notes = _check(docs, tmp_path)
    assert problems == [], problems
    assert notes == [], notes
    print("  matching bundled-plugin-env: no problems")


def test_placeholder_normalizer_maps_digest_and_empty() -> None:
    """The placeholder normalizer maps an all-zero digest to ``@<digest>`` (keeping
    the image name) and an empty value to ``<set by operator>``; a real value passes
    through unchanged so it is still compared."""
    assert (
        check_docs_refs._normalize_placeholder(f"docker.io/tai42/tai-sandbox-exec@{_ZERO_DIGEST}")
        == "docker.io/tai42/tai-sandbox-exec@<digest>"
    )
    assert check_docs_refs._normalize_placeholder("") == "<set by operator>"
    assert (
        check_docs_refs._normalize_placeholder("docker.io/tai42/x@sha256:abc123") == "docker.io/tai42/x@sha256:abc123"
    )
    print("  placeholder normalizer: digest and empty mapped, real value unchanged")


def test_bundled_plugin_env_placeholder_row_matches(tmp_path: Path) -> None:
    """An agents row using the placeholder convention (digest -> `@<digest>`, empty
    -> `<set by operator>`) matches the dist placeholders."""
    _write_dist_env(tmp_path, _FIXTURE_COMPOSE, _FIXTURE_ENV)
    docs = [("self-hosted/index.mdx", _bundled_env_doc(_MATCHING_ROWS))]
    problems, _ = _check(docs, tmp_path)
    agents_problems = [p for p in problems if "TAI_AGENTS_" in p]
    assert agents_problems == [], agents_problems
    print("  bundled-plugin-env placeholder rows: match")


def test_bundled_plugin_env_name_drift_behind_placeholder_flagged(tmp_path: Path) -> None:
    """A changed image NAME behind an all-zero digest is still caught: the digest
    normalizes but the name does not, so it does not equal the documented value."""
    drifted_env = _FIXTURE_ENV.replace("tai-sandbox-claude-code", "tai-sandbox-renamed")
    _write_dist_env(tmp_path, _FIXTURE_COMPOSE, drifted_env)
    docs = [("self-hosted/index.mdx", _bundled_env_doc(_MATCHING_ROWS))]
    problems, _ = _check(docs, tmp_path)
    assert any("TAI_AGENTS_CLAUDE_SESSION_IMAGE" in p and "!=" in p for p in problems), problems
    print("  bundled-plugin-env image name drift behind placeholder: flagged")


def test_bundled_plugin_env_real_value_behind_placeholder_flagged(tmp_path: Path) -> None:
    """A real value landing where the docs show a placeholder is caught: a non-empty
    secret does not normalize to `<set by operator>`."""
    real_env = _FIXTURE_ENV.replace("TAI_AGENTS_CLAUDE_API_KEY=\n", "TAI_AGENTS_CLAUDE_API_KEY=sk-real\n")
    _write_dist_env(tmp_path, _FIXTURE_COMPOSE, real_env)
    docs = [("self-hosted/index.mdx", _bundled_env_doc(_MATCHING_ROWS))]
    problems, _ = _check(docs, tmp_path)
    assert any("TAI_AGENTS_CLAUDE_API_KEY" in p and "!=" in p for p in problems), problems
    print("  bundled-plugin-env real value behind placeholder: flagged")


def test_bundled_plugin_env_value_drift_flagged(tmp_path: Path) -> None:
    """A documented value that differs from the dist value is flagged (docs->source)."""
    _write_dist_env(tmp_path, _FIXTURE_COMPOSE, _FIXTURE_ENV)
    rows = list(_MATCHING_ROWS)
    rows[0] = ("tai42-backend-arq", "ARQ_REDIS_URL", "redis://wrong:6379/0")
    docs = [("self-hosted/index.mdx", _bundled_env_doc(rows))]
    problems, _ = _check(docs, tmp_path)
    assert len(problems) == 1, problems
    assert "ARQ_REDIS_URL" in problems[0], problems[0]
    assert "!=" in problems[0], problems[0]
    print("  bundled-plugin-env value drift: flagged")


def test_bundled_plugin_env_missing_var_flagged(tmp_path: Path) -> None:
    """A preset in a bundled prefix that the table omits is flagged (source->docs)."""
    _write_dist_env(tmp_path, _FIXTURE_COMPOSE, _FIXTURE_ENV)
    docs = [("self-hosted/index.mdx", _bundled_env_doc(_MATCHING_ROWS[:2]))]
    problems, _ = _check(docs, tmp_path)
    assert any("missing" in p and "SANDBOX_LOCAL_ROOT" in p for p in problems), problems
    print("  bundled-plugin-env missing var: flagged")


def test_bundled_plugin_env_new_preset_under_bundled_prefix_flagged_missing(tmp_path: Path) -> None:
    """A preset ADDED to the compose for a bundled prefix, absent from the table, is
    flagged missing — the expected set follows the bundle, not a hand-kept list."""
    compose = _FIXTURE_COMPOSE.replace(
        "  ARQ_REDIS_URL: redis://redis:6379/0\n",
        "  ARQ_REDIS_URL: redis://redis:6379/0\n  ARQ_EXTRA: on\n",
    )
    _write_dist_env(tmp_path, compose, _FIXTURE_ENV)
    docs = [("self-hosted/index.mdx", _bundled_env_doc(_MATCHING_ROWS))]
    problems, _ = _check(docs, tmp_path)
    assert any("missing" in p and "ARQ_EXTRA" in p for p in problems), problems
    print("  bundled-plugin-env new preset under bundled prefix: flagged missing")


def test_bundled_plugin_env_extra_var_flagged(tmp_path: Path) -> None:
    """A table row for a variable outside every bundled prefix is flagged extra."""
    _write_dist_env(tmp_path, _FIXTURE_COMPOSE, _FIXTURE_ENV)
    rows = [*_MATCHING_ROWS, ("tai42-mystery", "MYSTERY_VAR", "x")]
    docs = [("self-hosted/index.mdx", _bundled_env_doc(rows))]
    problems, _ = _check(docs, tmp_path)
    assert any("not bundled-plugin presets" in p and "MYSTERY_VAR" in p for p in problems), problems
    print("  bundled-plugin-env extra var: flagged")


def test_bundled_plugin_env_absent_dist_notes(tmp_path: Path) -> None:
    """Offline (no dist compose/env) the check notes, never fails."""
    docs = [("self-hosted/index.mdx", _bundled_env_doc(_MATCHING_ROWS))]
    problems, notes = _check(docs, tmp_path)
    assert problems == [], problems
    assert len(notes) == 1, notes
    assert "not present offline" in notes[0], notes
    print("  bundled-plugin-env absent dist: noted, no failure")


# --- whole tree ------------------------------------------------------------


def test_current_tree_passes() -> None:
    """The committed docs tree has no reference drift (problems empty)."""
    problems, notes = check_docs_refs.evaluate()
    assert problems == [], "\n".join(problems)
    print(f"  current tree: no drift ({len(notes)} offline-gated note(s))")


def main() -> int:
    # Delegate to pytest so fixture-scoped tests and list-driven skips run correctly.
    return int(pytest.main([str(Path(__file__)), "-q"]))


if __name__ == "__main__":
    raise SystemExit(main())
