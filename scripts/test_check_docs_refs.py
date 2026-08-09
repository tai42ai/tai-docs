#!/usr/bin/env python3
"""Tests for the hand-written-reference drift-check.

Runnable from this project offline -- the valid-distribution set is read from the
committed ``plugins/_registry.json`` snapshot::

    uv run pytest scripts/test_check_docs_refs.py

Guarantees asserted:

1. A doc naming a real distribution / real repo passes.
2. A fabricated ``tai42-bogus`` distribution fails, naming its ``file:line``.
3. A documented ALWAYS_PUBLIC value that differs from the compose default fails.
4. The current committed tree passes (no drift).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_docs_refs  # noqa: E402


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


# --- whole tree ------------------------------------------------------------


def test_current_tree_passes() -> None:
    """The committed docs tree has no reference drift (problems empty)."""
    problems, notes = check_docs_refs.evaluate()
    assert problems == [], "\n".join(problems)
    print(f"  current tree: no drift ({len(notes)} offline-gated note(s))")


def main() -> int:
    print("test_check_docs_refs:")
    test_real_distribution_passes()
    test_bogus_distribution_fails()
    test_logo_asset_not_mistaken_for_distribution()
    test_slash_prefixed_bogus_distribution_flagged()
    test_monorepo_url_passes()
    test_monorepo_member_path_offline_notes()
    test_infra_repo_url_passes()
    test_bogus_repo_url_fails()
    test_mismatched_always_public_fails()
    test_matching_always_public_passes()
    test_double_quoted_always_public_verified()
    test_compose_regex_extracts_default()
    test_requirement_names_strips_extras_and_pins()
    test_current_tree_passes()
    print("test_check_docs_refs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
