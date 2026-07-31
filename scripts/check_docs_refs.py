#!/usr/bin/env python3
"""Reference drift-check: hand-written package/repo/config references in the docs
must never silently go stale against their sources of truth.

Unlike the generated reference (guarded by ``check_drift.py``), these values are
hand-authored in the narrative ``.mdx`` pages and can rot the moment a source
renames a distribution, a repository, or changes a compose default. This check
fails loudly -- exit non-zero, naming every offending ``file:line`` -- so a merged
source change that the docs did not follow is caught on the docs PR.

Four checks, all OFFLINE (no network); the three that depend on the
``tai-distribution`` sibling are gated on that checkout being present:

1. Distribution names -- every ``tai42-<name>`` mentioned in any ``.mdx`` file
   resolves to a real distribution. The authoritative set is the ``packages`` map
   in the packaged ``ecosystem.yml`` (the same offline source ``gen_catalog``
   renders), UNIONED with the foundation distributions this repository's own
   ``pyproject.toml`` ``[tool.uv.sources]`` floats as editable siblings
   (``tai42-contract`` / ``tai42-kit`` -- the layers that ship no catalog
   registration and so are absent from the packages map). A ``tai42-<name>``
   outside that set is drift.

2. Repo URLs -- every referenced repository resolves. Two shapes coexist: the
   ``tai42`` monorepo (``github.com/tai42ai/tai42``, optionally addressing a
   member directory via ``/tree/<ref>/<member-path>``), and a surviving
   standalone repo (``github.com/tai42ai/tai-<repo>``). The monorepo root always
   resolves; a member path is checked against the monorepo checkout when present
   (absent offline -> loud note, present -> hard check that the member directory
   exists). A standalone repo resolves if it is a package repo (the values side
   of the distribution->repo mapping), a known non-package repo (the
   ``INFRA_REPOS`` allowlist), or present as a local sibling checkout. Anything
   else is a HARD failure naming its ``file:line`` -- offline a typo is
   indistinguishable from a real repo, so an unknown repo fails closed rather
   than passing.

3. ALWAYS_PUBLIC example -- every documented
   ``ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES='[...]'`` value must EQUAL the
   default baked into ``tai-distribution``'s ``compose/docker-compose.yml``
   (``${ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES:-[...]}``), compared as parsed
   JSON. Gated on that compose file being present; absent -> loud note,
   present -> hard compare that names both values on mismatch.

4. Core image roster -- the self-hosted overview names the packages the release
   image bundles inside a delimited ``core-roster`` block (the ``ROSTER_MARKER_*``
   comments). That set, by distribution name (versions and extras ignored), must
   EQUAL the package set pinned in ``tai-distribution``'s
   ``docker/pypi-requirements.txt`` -- the file that IS the image's manifest of
   contents. A package added to or dropped from the image without the docs
   following is drift. Gated on the requirements file being present; absent ->
   loud note, present -> hard compare that names the missing/extra packages, and
   a present requirements file with no roster block in the docs is itself a
   failure (the sync point must exist). This is the mechanism that keeps the
   hand-written self-hosted page in step with the distribution: the reference
   regeneration pipeline only rebuilds generator-owned sections, never a narrative
   page, so a drift gate -- not a dispatch -- is what enforces this page's sync.

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

# The tai-distribution pinned first-party set: the file that IS the release
# image's manifest of contents. The self-hosted overview's core-roster block
# must name exactly this package set (by distribution name).
PYPI_REQUIREMENTS_REL = Path("tai-distribution") / "docker" / "pypi-requirements.txt"

# The delimited region in the docs that names the bundled core roster. The
# comparison reads only the distribution tokens BETWEEN these markers, so prose
# elsewhere naming a package (an "add it at runtime" example) never counts as a
# claim that the image bundles it.
ROSTER_MARKER_START = "core-roster:start"
ROSTER_MARKER_END = "core-roster:end"
_ROSTER_BLOCK_RE = re.compile(re.escape(ROSTER_MARKER_START) + r"(.*?)" + re.escape(ROSTER_MARKER_END), re.DOTALL)

# A `tai42-<name>` distribution token. The first lookahead forces a maximal
# token match (so no shorter prefix can be matched); the second excludes image
# asset paths such as `/tai42-logo-icon.png` (a `tai42-` token immediately
# followed by an image extension), which are icons, not distribution names. A
# slash prefix alone is NOT excluded, so a distribution token inside a URL is
# still detected.
_DIST_RE = re.compile(r"tai42-[a-z0-9]+(?:-[a-z0-9]+)*(?![a-z0-9-])(?!\.(?:png|svg|ico|jpe?g|gif|webp))")

# The monorepo that houses every first-party package. Its member directories are
# addressed as `github.com/tai42ai/tai42/tree/<ref>/<member-path>`.
MONOREPO = "tai42"

# A `github.com/tai42ai/tai42` reference, optionally addressing a member directory
# via `/tree/<ref>/<member-path>`. Group 1 is the member path when present, else
# the bare monorepo root. The member path stops at whitespace, `)`, or `#` so a
# trailing markdown/anchor delimiter never leaks into it.
_MONOREPO_RE = re.compile(r"github\.com/tai42ai/tai42(?:/tree/[^/\s)]+/([^\s)#]+))?")

# A surviving standalone `github.com/tai42ai/tai-<repo>` reference (https,
# git+https, or bare). The monorepo's own name (`tai42`) has no `tai-` prefix, so
# this pattern never matches it -- monorepo references go through `_MONOREPO_RE`.
_REPO_RE = re.compile(r"github\.com/tai42ai/(tai-[a-z0-9]+(?:-[a-z0-9]+)*)")

# A documented ALWAYS_PUBLIC assignment. The array may be single-quoted
# (`...PREFIXES='[...]'`, the shell form), double-quoted (`...PREFIXES="[...]"`),
# or a bare JSON array (`...PREFIXES=[...]`); the optional surrounding quote is
# tolerated in either style so the value is verified regardless of quoting.
_ALWAYS_PUBLIC_DOC_RE = re.compile(r"""ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES\s*=\s*['"]?(\[.*?\])['"]?""")

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
    # Scans line by line: documented values are single-line assignments by
    # convention, so a match never straddles a line break.
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


# The surviving standalone non-package repos — real repos that ship no PyPI
# distribution, so they never appear in the ecosystem dist->repo map. A curated
# allowlist: offline there is no other way to tell a real infra repo from a typo,
# so an unknown tai-<repo> must fail rather than pass silently. The package repos
# now live inside the `tai42` monorepo (validated via `_MONOREPO_RE`), so they are
# absent here. Keep in sync when a non-package repo is added to the org (adding
# one is far rarer than a doc typo).
INFRA_REPOS: frozenset[str] = frozenset(
    {
        "tai-studio",
        "tai-docs",
        "tai-distribution",
        "tai-marketplace",
        "tai-marketplace-web",
        "tai-website",
    }
)


def check_repo_urls(
    docs: list[tuple[str, str]],
    dist_map: dict[str, str],
    workspace_root: Path = WORKSPACE_ROOT,
) -> tuple[list[str], list[str]]:
    valid_repos = set(dist_map.values()) | INFRA_REPOS
    monorepo_root = workspace_root / MONOREPO
    problems: list[str] = []
    notes: list[str] = []
    unverified: list[str] = []
    for rel, text in docs:
        # Monorepo references: the bare root always resolves; a `/tree/.../member`
        # path is checked against the monorepo checkout when present.
        for lineno, member in _iter_matches(text, _MONOREPO_RE, group=1):
            if member is None:
                continue
            if not monorepo_root.is_dir():
                # Offline a subpath typo is indistinguishable from a real member,
                # and the monorepo tree is the only source of truth for it — note
                # and defer to the checkout-present run (the hosted docs CI).
                unverified.append(f"{rel}:{lineno}")
                continue
            if not (monorepo_root / member).is_dir():
                problems.append(
                    f"{rel}:{lineno}: github.com/tai42ai/{MONOREPO}/tree/.../{member} "
                    f"names no member directory in the {MONOREPO} checkout "
                    f"— likely a wrong or renamed member path"
                )
        # Surviving standalone repos: a known package repo, a known non-package
        # repo, or present as a sibling checkout -> real. Anything else fails
        # closed: offline a typo (github.com/tai42ai/tai-skeltn) is
        # indistinguishable from a real repo, so reject it rather than note-and-pass.
        for lineno, repo in _iter_matches(text, _REPO_RE, group=1):
            if repo in valid_repos or (workspace_root / repo).is_dir():
                continue
            problems.append(
                f"{rel}:{lineno}: github.com/tai42ai/{repo} is not a known repo "
                f"(not a package repo, not a known non-package repo, and no sibling checkout) "
                f"— likely a typo or a renamed/removed repo"
            )
    if unverified:
        notes.append(
            f"{MONOREPO} checkout not present offline; the monorepo member path(s) at "
            f"{', '.join(unverified)} were NOT verified against member directories "
            f"(a full checkout / the hosted docs CI verifies them)."
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


def _requirement_names(text: str) -> set[str]:
    """The distribution names pinned in a pypi-requirements file.

    Strips comments, extras (``[toolbox,files]``), and version specifiers, so
    ``tai42-skeleton[toolbox,files]==0.3.1`` yields ``tai42-skeleton``."""
    names: set[str] = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if m:
            names.add(m.group(1).lower())
    return names


def _roster_block(docs: list[tuple[str, str]]) -> tuple[str, int, set[str]] | None:
    """Locate the docs' delimited core-roster block.

    Returns ``(relative_path, start_lineno, distribution_tokens)`` for the first
    block found, or ``None`` when no page carries the markers."""
    for rel, text in docs:
        m = _ROSTER_BLOCK_RE.search(text)
        if not m:
            continue
        start_lineno = text[: m.start()].count("\n") + 1
        tokens = set(_DIST_RE.findall(m.group(1)))
        return rel, start_lineno, tokens
    return None


def check_core_roster(
    docs: list[tuple[str, str]],
    workspace_root: Path = WORKSPACE_ROOT,
) -> tuple[list[str], list[str]]:
    """Compare the docs' core-roster block against the image's pinned package set."""
    problems: list[str] = []
    notes: list[str] = []

    requirements = workspace_root / PYPI_REQUIREMENTS_REL
    if not requirements.is_file():
        notes.append(
            f"{PYPI_REQUIREMENTS_REL} not present offline; the self-hosted core-roster block "
            f"was NOT verified against the release image's pinned package set "
            f"(a full checkout / the hosted docs CI verifies it)."
        )
        return problems, notes

    expected = _requirement_names(requirements.read_text(encoding="utf-8"))
    block = _roster_block(docs)
    if block is None:
        problems.append(
            f"no core-roster block found in the docs (expected the '{ROSTER_MARKER_START}' / "
            f"'{ROSTER_MARKER_END}' markers on the self-hosted overview); the block MUST exist so "
            f"the bundled roster stays synced with {PYPI_REQUIREMENTS_REL}"
        )
        return problems, notes

    rel, lineno, documented = block
    missing = expected - documented
    extra = documented - expected
    if missing:
        problems.append(
            f"{rel}:{lineno}: core-roster block is missing package(s) the image bundles: "
            f"{', '.join(sorted(missing))} (pinned in {PYPI_REQUIREMENTS_REL})"
        )
    if extra:
        problems.append(
            f"{rel}:{lineno}: core-roster block names package(s) the image does NOT bundle: "
            f"{', '.join(sorted(extra))} (absent from {PYPI_REQUIREMENTS_REL})"
        )
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

    p, n = check_core_roster(docs, workspace_root)
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

    print(
        "check_docs_refs: OK -- distribution names, repo URLs, the ALWAYS_PUBLIC example, "
        "and the core-roster block all match source."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
