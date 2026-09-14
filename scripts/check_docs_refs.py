#!/usr/bin/env python3
"""Reference drift-check: hand-written package/repo/config references in the docs
must never silently go stale against their sources of truth.

Unlike the generated reference (guarded by ``check_drift.py``), these values are
hand-authored in the narrative ``.mdx`` pages and can rot the moment a source
renames a distribution, a repository, or changes a compose default. This check
fails loudly -- exit non-zero, naming every offending ``file:line`` -- so a merged
source change that the docs did not follow is caught on the docs push/PR gate and
on the dispatch-triggered run.

Five checks, all NETWORK-FREE; each hand-written fact is gated on the source it
needs. Check 2's monorepo member paths need the ``tai42`` monorepo checkout; the
three that read the ``tai-distribution`` sibling (checks 3, 4, 5) are gated on
that checkout; and check 5 additionally reads the settings registry, so it runs
from the monorepo skeleton environment and fails LOUDLY — rather than skipping —
when the registry cannot be loaded while tai-distribution is present:

1. Distribution names -- every ``tai42-<name>`` mentioned in any ``.mdx`` file
   resolves to a real distribution. The authoritative set is every listing's
   ``package`` in the committed ``plugins/_registry.json`` (the marketplace
   snapshot ``gen_plugins`` emits), UNIONED with the foundation distributions this
   repository's own ``pyproject.toml`` ``[tool.uv.sources]`` floats as editable
   siblings (``tai42-skeleton`` / ``tai42-contract`` / ``tai42-kit`` -- the core
   layers that are not marketplace listings and so are absent from the registry).
   A ``tai42-<name>`` outside that set is drift.

2. Repo URLs -- every referenced repository resolves. Two shapes coexist: the
   ``tai42`` monorepo (``github.com/tai42ai/tai42``, optionally addressing a
   member directory via ``/tree/<ref>/<member-path>``), and a standalone
   repo (``github.com/tai42ai/tai-<repo>``). The monorepo root always
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

5. Bundled-plugin env presets -- the self-hosted overview names, inside a delimited
   ``bundled-plugin-env`` block, the env variable each bundled non-core plugin reads
   and the value the compose bundle ships for it. The EXPECTED variable set is
   derived, never hand-kept: every env key the bundle presets (the ``x-tai-app-env``
   anchor, each service's own ``environment`` block, and the uncommented keys of
   ``compose/.env.example``) that falls in a BUNDLED plugin's env namespace. Bundled
   = the plugins pinned in ``docker/pypi-requirements.txt``; a plugin's env namespace
   is the prefixes its settings groups declare (read from the settings registry after
   importing the bundled plugins' modules the same way the generator does), plus the
   exact vars of any group that declares an empty prefix. Every documented value must
   EQUAL what ``tai-distribution`` sets -- the ``compose/.env.example`` value when the
   template sets the variable, else the compose preset -- and the block must name
   exactly the derived set (no more, no fewer). Gated on the compose file, env
   template, and requirements file being present; absent -> loud note. When they are
   present but the settings registry cannot be loaded (the bundled plugin packages
   are not installed), the check FAILS LOUDLY naming the missing distributions and
   saying to run from the monorepo skeleton environment, never a silent skip.
   Present + loadable -> hard compare naming every mismatch/missing/extra and the
   source path. A preset value changed in either repo without the other following,
   or a variable entering/leaving a bundled plugin's namespace, is caught here.

   Operator-fill placeholders follow ONE convention so an all-zero digest or an
   empty secret cannot churn the exact compare: the table shows a stable token and
   the gate maps the source placeholder to that token BEFORE comparing -- an all-zero
   ``@sha256:<64 zeros>`` image digest becomes ``@<digest>`` and an empty value
   becomes ``<set by operator>``. The image NAME before the ``@`` and every
   non-placeholder value stay exact, so a renamed image or a real value landing in
   the source is still caught.

The distribution set (check 1) is read from the committed registry snapshot, so
checks 1-4 need no source env; check 5 imports the bundled plugins' settings, so
run the whole check from the monorepo skeleton environment (``uv sync
--all-packages --all-extras``) when tai-distribution is present::

    cd tai42/core/skeleton && uv run python ../../../tai-docs/scripts/check_docs_refs.py
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from _plugin_settings import BundledEnvNamespaces

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
WORKSPACE_ROOT = DOCS_ROOT.parent
sys.path.insert(0, str(SCRIPT_DIR))

from registry import load_registry  # noqa: E402

# The tai-distribution compose bundle: the authoritative home of the
# ACCESS_CONTROL_ALWAYS_PUBLIC_PATH_PREFIXES default the docs mirror.
COMPOSE_REL = Path("tai-distribution") / "compose" / "docker-compose.yml"

# The tai-distribution pinned first-party set: the file that IS the release
# image's manifest of contents. The self-hosted overview's core-roster block
# must name exactly this package set (by distribution name).
PYPI_REQUIREMENTS_REL = Path("tai-distribution") / "docker" / "pypi-requirements.txt"

# The tai-distribution installer-set env template: the source of the operator
# values the compose reads (``KEY=value``), paired with the compose anchor.
ENV_EXAMPLE_REL = Path("tai-distribution") / "compose" / ".env.example"

# The delimited region in the docs that names the bundled core roster. The
# comparison reads only the distribution tokens BETWEEN these markers, so prose
# elsewhere naming a package (an "add it at runtime" example) never counts as a
# claim that the image bundles it.
ROSTER_MARKER_START = "core-roster:start"
ROSTER_MARKER_END = "core-roster:end"
_ROSTER_BLOCK_RE = re.compile(re.escape(ROSTER_MARKER_START) + r"(.*?)" + re.escape(ROSTER_MARKER_END), re.DOTALL)

# The delimited region naming, per bundled plugin, the env var the compose bundle
# presets and the value it sets. The comparison reads only rows BETWEEN these
# markers, so prose elsewhere naming one of these variables never counts.
BUNDLED_PLUGIN_ENV_MARKER_START = "bundled-plugin-env:start"
BUNDLED_PLUGIN_ENV_MARKER_END = "bundled-plugin-env:end"
_BUNDLED_PLUGIN_ENV_BLOCK_RE = re.compile(
    re.escape(BUNDLED_PLUGIN_ENV_MARKER_START) + r"(.*?)" + re.escape(BUNDLED_PLUGIN_ENV_MARKER_END), re.DOTALL
)

# Placeholder convention for values the operator MUST fill: the dist ships an
# operator-fill placeholder that would otherwise churn (a fresh digest, a real
# secret) and break an exact compare, so the table shows a stable reference token
# and the gate maps the source placeholder to that same token BEFORE comparing.
# The image NAME (everything before ``@``) and every non-placeholder value stay
# exact, so a name drift or a real value landing in the source is still caught.
#   - an all-zero ``@sha256:<64 zeros>`` image digest -> ``@<digest>``
#   - an empty value -> ``<set by operator>``
_PLACEHOLDER_SET_BY_OPERATOR = "<set by operator>"
_ZERO_DIGEST_RE = re.compile(r"@sha256:0{64}\b")


def _normalize_placeholder(value: str) -> str:
    """Map a dist operator-fill placeholder to its stable table token; other values
    pass through unchanged (so a name change or a real value is still compared)."""
    if value == "":
        return _PLACEHOLDER_SET_BY_OPERATOR
    return _ZERO_DIGEST_RE.sub("@<digest>", value)


# A `| `pkg` | `VAR` | `value` |` row inside the bundled-plugin-env block: three
# code-span cells (package, variable, value). The value cell is captured up to its
# closing backtick so trailing prose in the same cell is ignored.
_BUNDLED_PLUGIN_ENV_ROW_RE = re.compile(r"\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`")

# A `${VAR:-default}` (optional default) or `${VAR:?msg}` (required, no default)
# substitution, with the surrounding quotes already stripped by the YAML load.
_COMPOSE_SUBST_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(?P<op>:-|:\?)(?P<rest>.*)\}$")

# A `tai42-<name>` distribution token. The leading lookbehind anchors the token at
# the start of its hyphenated word, so a LONGER identifier that merely ENDS in a
# distribution-shaped suffix is not mistaken for one -- the vendor annotation
# `x-tai42-expression` names no distribution. It mirrors the trailing lookahead:
# a distribution token is a whole hyphen-word, never a substring of one. The
# first lookahead forces a maximal token match (so no shorter
# prefix can be matched); the second excludes image asset paths such as
# `/tai42-logo-icon.png` (a `tai42-` token immediately followed by an image
# extension), which are icons, not distribution names. A slash prefix alone is NOT
# excluded, so a distribution token inside a URL is still detected.
_DIST_RE = re.compile(r"(?<![a-z0-9-])tai42-[a-z0-9]+(?:-[a-z0-9]+)*(?![a-z0-9-])(?!\.(?:png|svg|ico|jpe?g|gif|webp))")

# The monorepo that houses every first-party package. Its member directories are
# addressed as `github.com/tai42ai/tai42/tree/<ref>/<member-path>`.
MONOREPO = "tai42"

# A `github.com/tai42ai/tai42` reference, optionally addressing a member directory
# via `/tree/<ref>/<member-path>`. Group 1 is the member path when present, else
# the bare monorepo root. The member path stops at whitespace, `)`, or `#` so a
# trailing markdown/anchor delimiter never leaks into it.
_MONOREPO_RE = re.compile(r"github\.com/tai42ai/tai42(?:/tree/[^/\s)]+/([^\s)#]+))?")

# A standalone `github.com/tai42ai/tai-<repo>` reference (https,
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


# The generated Plugins section is authored by plugin publishers, not by this
# repo, and carries their own package/repo tokens (a plugin may name a PyPI
# distribution outside the tai42 listing set). It is a GENERATED tree, not a
# hand-written reference, so it is out of scope for this drift gate.
_GENERATED_DIRS = ("plugins/",)


def scan_docs(docs_root: Path = DOCS_ROOT) -> list[tuple[str, str]]:
    """Return ``(relative_path, text)`` for every hand-authored ``.mdx`` file."""
    out: list[tuple[str, str]] = []
    for p in sorted(docs_root.rglob("*.mdx")):
        rel = str(p.relative_to(docs_root))
        if rel.startswith(_GENERATED_DIRS):
            continue
        out.append((rel, p.read_text(encoding="utf-8")))
    return out


def _pyproject_sources(docs_root: Path) -> dict[str, str]:
    """The foundation ``tai42-<name> -> tai-<repo>`` pairs this repo floats as
    editable siblings in ``pyproject.toml`` ``[tool.uv.sources]``.

    These are the distributions the docs build itself depends on (the contract,
    kit, and cli foundation layers) that ship no marketplace listing and so never appear in
    the ``plugins/_registry.json`` snapshot."""
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
    """The authoritative valid-distribution set, assembled offline.

    Primary source: every listing's ``package`` in ``plugins/_registry.json``
    (every distribution the marketplace lists). Unioned with the foundation
    distributions declared in this repo's own ``pyproject.toml`` sources, so the
    core skeleton/contract/kit/cli layers -- real distributions that are not
    marketplace listings -- resolve too. The values are unused (only the key set
    gates distribution names), so each registry package maps to itself. A
    descriptor-only listing has ``package`` null (it ships no distribution), so it
    is skipped -- a null must never seed a spurious ``None -> None`` entry."""
    mapping: dict[str, str] = {
        listing["package"]: listing["package"] for listing in load_registry() if listing.get("package") is not None
    }
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
                    f"(absent from plugins/_registry.json packages and this repo's pyproject sources)"
                )
    return problems


# The standalone non-package repos — real repos that ship no PyPI
# distribution, so they never appear in the ``plugins/_registry.json`` snapshot. A curated
# allowlist: offline there is no other way to tell a real infra repo from a typo,
# so an unknown tai-<repo> must fail rather than pass silently. The package repos
# are members of the `tai42` monorepo (validated via `_MONOREPO_RE`), so they are
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
    workspace_root: Path = WORKSPACE_ROOT,
) -> tuple[list[str], list[str]]:
    valid_repos = INFRA_REPOS
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
        # Surviving standalone repos: a known non-package repo, or present as a
        # sibling checkout -> real. Anything else fails closed: offline a typo
        # (github.com/tai42ai/tai-skeltn) is indistinguishable from a real repo,
        # so reject it rather than note-and-pass. Package repos are monorepo
        # members, resolved above via `_MONOREPO_RE`, never here.
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


def _parse_env_example(text: str) -> dict[str, str]:
    """The uncommented ``KEY=value`` assignments in a compose ``.env.example``.

    A commented line (``# ...``) sets nothing; an empty value (``KEY=``) records the
    empty string (the operator must fill it). Values are taken verbatim."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        if sep and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            values[key] = value
    return values


def _resolve_compose_subst(value: str) -> str | None:
    """A compose value with its ``${VAR:-default}`` / ``${VAR:?msg}`` resolved.

    ``${VAR:-default}`` yields the default (possibly empty); ``${VAR:?msg}``
    (required, no default) yields ``None``; a literal yields itself. The YAML load
    already stripped any surrounding quotes."""
    subst = _COMPOSE_SUBST_RE.match(value)
    if subst:
        return None if subst.group("op") == ":?" else subst.group("rest")
    return value


def _compose_env_presets(compose_text: str) -> dict[str, str | None]:
    """Every env key the compose bundle presets and its resolved value.

    The shared ``x-tai-app-env`` anchor merged with each service's own
    ``environment`` block (YAML resolves the anchor merge), each value resolved
    through :func:`_resolve_compose_subst`. A key two services set to disagreeing
    values is a source ambiguity and raises rather than silently picking one."""
    data = yaml.safe_load(compose_text)
    env_blocks: list[dict] = []
    anchor = data.get("x-tai-app-env")
    if isinstance(anchor, dict):
        env_blocks.append(anchor)
    for service in (data.get("services") or {}).values():
        env = service.get("environment") if isinstance(service, dict) else None
        if isinstance(env, dict):
            env_blocks.append(env)
    raw: dict[str, str] = {}
    for block in env_blocks:
        for key, value in block.items():
            text = "" if value is None else str(value)
            if key in raw and raw[key] != text:
                raise RuntimeError(f"{COMPOSE_REL}: {key} is preset to conflicting values {raw[key]!r} and {text!r}")
            raw[key] = text
    return {key: _resolve_compose_subst(text) for key, text in raw.items()}


def _installed_dist_names() -> set[str]:
    """The lower-cased names of every installed distribution in this environment."""
    return {(dist.metadata["Name"] or "").lower() for dist in importlib.metadata.distributions()}


def _load_bundled_namespaces(requirements: Path) -> BundledEnvNamespaces:
    """The env namespaces owned by the bundled plugins' settings groups.

    Bundled = the distributions pinned in ``docker/pypi-requirements.txt``. Their
    settings modules are imported the same way the generator does (through the
    shared plugin-settings module), then each group's env prefix is read from the
    registry. FAILS LOUDLY — never a silent skip — when a bundled plugin package is
    not installed or a bundled module is not importable, naming what is missing and
    saying to run from the monorepo skeleton environment."""
    bundled_dists = _requirement_names(requirements.read_text(encoding="utf-8"))
    try:
        from tai42_skeleton.app.route_registry import load_api_routes

        import _plugin_settings
    except ImportError as exc:
        raise RuntimeError(
            f"the settings registry is not importable ({exc}); run the bundled-plugin-env check from the "
            "monorepo skeleton environment (cd tai42/core/skeleton && uv sync --all-packages --all-extras)"
        ) from exc

    missing = bundled_dists - _installed_dist_names()
    if missing:
        raise RuntimeError(
            f"bundled plugin distribution(s) {sorted(missing)} (pinned in {PYPI_REQUIREMENTS_REL}) are not installed "
            "in this environment, so their settings env prefixes cannot be read; run the bundled-plugin-env check "
            "from the monorepo skeleton environment (cd tai42/core/skeleton && uv sync --all-packages --all-extras)"
        )

    load_api_routes()
    plugins = _plugin_settings.discover_plugins()
    bundled_plugins = [info for name, info in plugins.items() if name.lower() in bundled_dists]
    _plugin_settings.import_plugin_settings(bundled_plugins)
    return _plugin_settings.bundled_env_namespaces({info.top_level for info in bundled_plugins})


def _bundled_plugin_env_expected(
    compose_text: str, env_text: str, namespaces: BundledEnvNamespaces
) -> dict[str, str | None]:
    """The variables the bundle presets that fall in a bundled plugin's env
    namespace, mapped to the value the bundle ships: the ``.env.example`` value when
    the template sets the variable, else the compose preset (anchor or a service's
    ``environment`` block)."""
    compose_presets = _compose_env_presets(compose_text)
    env_example = _parse_env_example(env_text)
    expected: dict[str, str | None] = {}
    for key in set(compose_presets) | set(env_example):
        if not namespaces.owns(key):
            continue
        expected[key] = env_example[key] if key in env_example else compose_presets.get(key)
    return expected


def _bundled_plugin_env_block(docs: list[tuple[str, str]]) -> tuple[str, int, list[tuple[str, str, str]]] | None:
    """Locate the docs' bundled-plugin-env block and its ``(package, var, value)`` rows.

    Returns ``(relative_path, start_lineno, rows)`` for the first block found, or
    ``None`` when no page carries the markers."""
    for rel, text in docs:
        m = _BUNDLED_PLUGIN_ENV_BLOCK_RE.search(text)
        if not m:
            continue
        start_lineno = text[: m.start()].count("\n") + 1
        rows = [(pkg, var, value) for pkg, var, value in _BUNDLED_PLUGIN_ENV_ROW_RE.findall(m.group(1))]
        return rel, start_lineno, rows
    return None


def check_bundled_plugin_env(
    docs: list[tuple[str, str]],
    workspace_root: Path = WORKSPACE_ROOT,
    *,
    namespaces: BundledEnvNamespaces | None = None,
) -> tuple[list[str], list[str]]:
    """Compare the docs' bundled-plugin-env block against the value the bundle ships
    for every variable in a bundled plugin's env namespace.

    Exact both ways over the derived expected set (see
    :func:`_bundled_plugin_env_expected`): every variable must be documented with a
    value equal to what the dist ships (the ``.env.example`` value when the template
    sets it, else the compose preset), and the block may name no other variable.
    Gated on the compose file, env template, and requirements file being present;
    absent -> loud note. ``namespaces`` is derived from the settings registry when
    not supplied (tests inject a synthetic set); the derivation FAILS LOUDLY when the
    registry cannot be loaded."""
    problems: list[str] = []
    notes: list[str] = []

    block = _bundled_plugin_env_block(docs)
    compose = workspace_root / COMPOSE_REL
    env_example = workspace_root / ENV_EXAMPLE_REL
    requirements = workspace_root / PYPI_REQUIREMENTS_REL

    if not compose.is_file() or not env_example.is_file():
        if block is not None:
            notes.append(
                f"{COMPOSE_REL} / {ENV_EXAMPLE_REL} not present offline; the bundled-plugin-env block "
                f"at {block[0]}:{block[1]} was NOT verified against the dist compose presets "
                f"(a full checkout / the hosted docs CI verifies it)."
            )
        return problems, notes

    if namespaces is None:
        if not requirements.is_file():
            if block is not None:
                notes.append(
                    f"{PYPI_REQUIREMENTS_REL} not present offline; the bundled-plugin-env block "
                    f"at {block[0]}:{block[1]} was NOT verified (the bundled set cannot be resolved without it)."
                )
            return problems, notes
        namespaces = _load_bundled_namespaces(requirements)

    expected = _bundled_plugin_env_expected(
        compose.read_text(encoding="utf-8"), env_example.read_text(encoding="utf-8"), namespaces
    )

    if block is None:
        problems.append(
            f"no bundled-plugin-env block found in the docs (expected the '{BUNDLED_PLUGIN_ENV_MARKER_START}' / "
            f"'{BUNDLED_PLUGIN_ENV_MARKER_END}' markers on the self-hosted overview); the block MUST exist so "
            f"the bundled plugins' compose values stay synced with {COMPOSE_REL} / {ENV_EXAMPLE_REL}"
        )
        return problems, notes

    rel, lineno, rows = block
    documented = {var: value for _, var, value in rows}

    extra = set(documented) - set(expected)
    if extra:
        problems.append(
            f"{rel}:{lineno}: bundled-plugin-env block names variable(s) that are not bundled-plugin presets: "
            f"{', '.join(sorted(extra))}"
        )
    missing = set(expected) - set(documented)
    if missing:
        problems.append(
            f"{rel}:{lineno}: bundled-plugin-env block is missing bundled-plugin preset(s): "
            f"{', '.join(sorted(missing))}"
        )

    for var in sorted(set(expected) & set(documented)):
        want = _normalize_placeholder(expected[var] or "")
        if documented[var] != want:
            problems.append(
                f"{rel}:{lineno}: {var} documented value {documented[var]!r} != dist value {want!r} "
                f"(from {ENV_EXAMPLE_REL} / {COMPOSE_REL})"
            )

    return problems, notes


def evaluate(
    docs_root: Path = DOCS_ROOT,
    workspace_root: Path = WORKSPACE_ROOT,
) -> tuple[list[str], list[str]]:
    """Run every check over the tree; return ``(problems, notes)``."""
    dist_map = load_distribution_map(docs_root)
    docs = scan_docs(docs_root)

    problems: list[str] = []
    notes: list[str] = []

    problems += check_distribution_names(docs, set(dist_map))

    p, n = check_repo_urls(docs, workspace_root)
    problems += p
    notes += n

    p, n = check_always_public(docs, workspace_root)
    problems += p
    notes += n

    p, n = check_core_roster(docs, workspace_root)
    problems += p
    notes += n

    p, n = check_bundled_plugin_env(docs, workspace_root)
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
            "(plugins/_registry.json packages, the tai42ai repos, or the compose default).",
            file=sys.stderr,
        )
        return 1

    print(
        "check_docs_refs: OK -- distribution names, repo URLs, the ALWAYS_PUBLIC example, "
        "the core-roster block, and the bundled-plugin-env block all match source."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
