#!/usr/bin/env python3
"""Reference drift-check: hand-written package/repo/config references in the docs
must never silently go stale against their sources of truth.

Unlike the generated reference (guarded by ``check_drift.py``), these values are
hand-authored in the narrative ``.mdx`` pages and can rot the moment a source
renames a distribution, a repository, or changes a compose default. This check
fails loudly -- exit non-zero, naming every offending ``file:line`` -- so a merged
source change that the docs did not follow is caught on the docs PR.

Three checks, all OFFLINE (no network); the two that depend on the
``tai-distribution`` sibling are gated on that checkout being present:

1. Distribution names -- every ``tai42-<name>`` mentioned in any ``.mdx`` file
   resolves to a real distribution. The authoritative set is the ``packages`` map
   in the packaged ``ecosystem.yml`` (the same offline source ``gen_catalog``
   renders), UNIONED with the foundation distributions this repository's own
   ``pyproject.toml`` ``[tool.uv.sources]`` floats as editable siblings
   (``tai42-contract`` / ``tai42-kit`` -- the layers that ship no catalog
   registration and so are absent from the packages map). A ``tai42-<name>``
   outside that set is drift.

2. Repo URLs -- every ``github.com/tai42ai/tai-<repo>`` referenced resolves to a
   real repository. Package repos are validated against the values side of the
   same distribution->repo mapping. A repo that is NOT a package repo (an infra
   repo such as ``tai-distribution``) is verified against a sibling checkout when
   present; when absent it is reported as UNVERIFIED with a loud note (never
   silently passed).

3. ALWAYS_PUBLIC example -- every documented
   ``ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES='[...]'`` value must EQUAL the
   default baked into ``tai-distribution``'s ``compose/docker-compose.yml``
   (``${ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES:-[...]}``), compared as parsed
   JSON. Gated on that compose file being present; absent -> loud note,
   present -> hard compare that names both values on mismatch.

Run it where ``tai42_skeleton`` resolves (this project's dev env or the
tai42-skeleton virtualenv)::

    uv run python scripts/check_docs_refs.py
    cd tai-skeleton && uv run python ../tai-docs/scripts/check_docs_refs.py
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
WORKSPACE_ROOT = DOCS_ROOT.parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_catalog  # noqa: E402

# The tai-distribution compose bundle: the authoritative home of the
# ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES default the docs mirror.
COMPOSE_REL = Path("tai-distribution") / "compose" / "docker-compose.yml"

# A `tai42-<name>` distribution token. The negative lookbehind on `/` keeps the
# static asset path `/tai42-logo-icon.png` (which appears inside the
# ALWAYS_PUBLIC example list) from being mistaken for a distribution name.
_DIST_RE = re.compile(r"(?<!/)tai42-[a-z0-9]+(?:-[a-z0-9]+)*")

# A `github.com/tai42ai/tai-<repo>` reference (https, git+https, or bare).
_REPO_RE = re.compile(r"github\.com/tai42ai/(tai-[a-z0-9]+(?:-[a-z0-9]+)*)")

# A documented ALWAYS_PUBLIC assignment: `...PREFIXES='[...]'`.
_ALWAYS_PUBLIC_DOC_RE = re.compile(r"ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES\s*=\s*'(\[.*?\])'")

# The compose default: `...PREFIXES: '${...:-[...]}'`.
_ALWAYS_PUBLIC_COMPOSE_RE = re.compile(
    r"ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES:\s*'\$\{ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES:-(\[.*?\])\}'"
)


def scan_docs(docs_root: Path = DOCS_ROOT) -> list[tuple[str, str]]:
    """Return ``(relative_path, text)`` for every ``.mdx`` file under the docs root."""
    return [(str(p.relative_to(docs_root)), p.read_text(encoding="utf-8")) for p in sorted(docs_root.rglob("*.mdx"))]


def _pyproject_sources(docs_root: Path) -> dict[str, str]:
    """The foundation ``tai42-<name> -> tai-<repo>`` pairs this repo floats as
    editable siblings in ``pyproject.toml`` ``[tool.uv.sources]``.

    These are the distributions the docs build itself depends on (the contract and
    kit foundation layers) that ship no catalog registration and so never appear in
    the packaged ecosystem's ``packages`` map."""
    data = tomllib.loads((docs_root / "pyproject.toml").read_text(encoding="utf-8"))
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    mapping: dict[str, str] = {}
    for dist, spec in sources.items():
        if not dist.startswith("tai42-") or not isinstance(spec, dict):
            continue
        path = spec.get("path", "")
        repo = path.rstrip("/").rsplit("/", 1)[-1]
        if repo:
            mapping[dist] = repo
    return mapping


def load_distribution_map(docs_root: Path = DOCS_ROOT) -> dict[str, str]:
    """The authoritative ``distribution -> repo`` mapping, assembled offline.

    Primary source: the ``packages`` map in the packaged ``ecosystem.yml`` (every
    distribution that ships a catalog registration). Unioned with the foundation
    distributions declared in this repo's own ``pyproject.toml`` sources, so the
    contract/kit layers -- real distributions absent from the registration map --
    resolve too."""
    doc = gen_catalog.load_ecosystem()
    packages = doc.get("packages")
    if not isinstance(packages, dict) or not packages:
        print("check_docs_refs: ecosystem.yml has no packages mapping", file=sys.stderr)
        raise SystemExit(1)
    mapping = dict(packages)
    for dist, repo in _pyproject_sources(docs_root).items():
        mapping.setdefault(dist, repo)
    return mapping


def _iter_matches(text: str, pattern: re.Pattern[str], group: int = 0):
    """Yield ``(lineno, matched_value)`` for every match, 1-based line numbers."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in pattern.finditer(line):
            yield lineno, m.group(group)


def check_distribution_names(docs: list[tuple[str, str]], valid_dists: set[str]) -> list[str]:
    problems: list[str] = []
    for rel, text in docs:
        for lineno, name in _iter_matches(text, _DIST_RE):
            if name not in valid_dists:
                problems.append(
                    f"{rel}:{lineno}: '{name}' is not a real distribution "
                    f"(absent from ecosystem.yml packages and this repo's pyproject sources)"
                )
    return problems


# The org's non-package repos — real repos that ship no PyPI distribution, so
# they never appear in the ecosystem dist->repo map. A curated allowlist: offline
# there is no other way to tell a real infra repo from a typo, so an unknown
# tai-<repo> must fail rather than pass silently. Keep in sync when a non-package
# repo is added to the org (adding one is far rarer than a doc typo).
INFRA_REPOS: frozenset[str] = frozenset(
    {
        "tai-studio",
        "tai-docs",
        "tai-distribution",
        "tai-e2e",
        "tai-marketplace",
        "tai-marketplace-web",
        "tai-website",
        "tai-babelfish-kit",
        "tai-babelfish-flows",
    }
)


def check_repo_urls(
    docs: list[tuple[str, str]],
    dist_map: dict[str, str],
    workspace_root: Path = WORKSPACE_ROOT,
) -> tuple[list[str], list[str]]:
    valid_repos = set(dist_map.values()) | INFRA_REPOS
    problems: list[str] = []
    notes: list[str] = []
    for rel, text in docs:
        for lineno, repo in _iter_matches(text, _REPO_RE, group=1):
            # A known package repo, a known non-package repo, or present as a
            # sibling checkout -> real. Anything else fails closed: offline a typo
            # (github.com/tai42ai/tai-skeltn) is indistinguishable from a real repo,
            # so reject it rather than note-and-pass.
            if repo in valid_repos or (workspace_root / repo).is_dir():
                continue
            problems.append(
                f"{rel}:{lineno}: github.com/tai42ai/{repo} is not a known repo "
                f"(not a package repo, not a known non-package repo, and no sibling checkout) "
                f"— likely a typo or a renamed/removed repo"
            )
    return problems, notes


def compare_always_public(docs: list[tuple[str, str]], default: list) -> list[str]:
    """Compare every documented ALWAYS_PUBLIC value against ``default`` (parsed JSON)."""
    problems: list[str] = []
    for rel, text in docs:
        for lineno, raw in _iter_matches(text, _ALWAYS_PUBLIC_DOC_RE, group=1):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                problems.append(
                    f"{rel}:{lineno}: ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES value is not valid JSON: {exc}"
                )
                continue
            if parsed != default:
                problems.append(
                    f"{rel}:{lineno}: ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES example "
                    f"{json.dumps(parsed)} != compose default {json.dumps(default)}"
                )
    return problems


def check_always_public(
    docs: list[tuple[str, str]],
    workspace_root: Path = WORKSPACE_ROOT,
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []
    doc_hits = [
        f"{rel}:{lineno}" for rel, text in docs for lineno, _ in _iter_matches(text, _ALWAYS_PUBLIC_DOC_RE, group=1)
    ]

    compose = workspace_root / COMPOSE_REL
    if not compose.is_file():
        if doc_hits:
            notes.append(
                f"{COMPOSE_REL} not present offline; the ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES "
                f"example(s) at {', '.join(doc_hits)} were NOT verified against the compose default "
                f"(a full checkout / the hosted docs CI verifies them)."
            )
        return problems, notes

    m = _ALWAYS_PUBLIC_COMPOSE_RE.search(compose.read_text(encoding="utf-8"))
    if not m:
        problems.append(
            f"{COMPOSE_REL}: no ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES default found; the "
            f"documented example(s) cannot be verified against source (did the compose var change?)"
        )
        return problems, notes

    try:
        default = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        problems.append(f"{COMPOSE_REL}: ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES default is not valid JSON: {exc}")
        return problems, notes

    problems += compare_always_public(docs, default)
    return problems, notes


def evaluate(
    docs_root: Path = DOCS_ROOT,
    workspace_root: Path = WORKSPACE_ROOT,
) -> tuple[list[str], list[str]]:
    """Run all three checks over the tree; return ``(problems, notes)``."""
    dist_map = load_distribution_map(docs_root)
    docs = scan_docs(docs_root)

    problems: list[str] = []
    notes: list[str] = []

    problems += check_distribution_names(docs, set(dist_map))

    p, n = check_repo_urls(docs, dist_map, workspace_root)
    problems += p
    notes += n

    p, n = check_always_public(docs, workspace_root)
    problems += p
    notes += n

    return problems, notes


def main() -> int:
    problems, notes = evaluate()

    for note in notes:
        print(f"check_docs_refs: NOTE -- {note}")

    if problems:
        print("check_docs_refs: DRIFT -- hand-written references disagree with their sources:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nUpdate the offending docs to match the source of truth "
            "(ecosystem.yml packages, the tai42ai repos, or the compose default).",
            file=sys.stderr,
        )
        return 1

    print("check_docs_refs: OK -- distribution names, repo URLs, and the ALWAYS_PUBLIC example all match source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
