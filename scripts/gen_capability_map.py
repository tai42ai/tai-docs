#!/usr/bin/env python3
"""Generate the capability map — a code-anchored index of every platform capability.

One generated page, ``reference/capability-map.mdx``, with a FIXED set of H2
feature areas. The implementer invents NO taxonomy and NO prose: each area draws
one row per capability from a machine-readable source, and each one-liner is
pinned to a source field VERIFIED to exist (a verbatim summary/description where
the model carries one, a deterministic name-derived label where it does not).

Areas and their sources:

* ``HTTP API`` — one row per OpenAPI operation, grouped by tag; the one-liner is
  the operation ``summary`` VERBATIM (a missing summary is a loud failure naming
  the route — first-party docstring hygiene).
* ``Plugins`` — one row per ``plugins/_registry.json`` item; the one-liner is the
  item ``description`` VERBATIM.
* ``Settings`` — one row per registered settings group; the registry model carries
  no description, so the one-liner is the name-derived ``"<Titleized> settings
  (<module>)"`` (a name already ending in "Settings" keeps its single suffix).
* ``Agents & extensions`` — agent rows use the registration description VERBATIM;
  extension rows carry only ``{name, kind}`` so the one-liner is the name-derived
  ``"<Titleized> (<kind>)"``. In the bare regen env the live registry is empty and
  the area renders empty (agent-kind plugins stay covered under Plugins).

There is NO ``Channels`` area: the channel capability flags are bare class-level
booleans, non-enumerable; channel capabilities surface through the Plugins rows.
babelfish and every private-repo internal are excluded — only the public monorepo
surfaces above feed the page.

A source that fails to resolve is a loud nonzero exit; the loud-fail rule is for
unresolvable sources or a missing REQUIRED field, never for an empty result.

Run it where ``tai42_skeleton`` resolves (the tai42-skeleton virtualenv)::

    cd tai42/core/skeleton && uv run python ../../../tai-docs/scripts/gen_capability_map.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
OPENAPI = DOCS_ROOT / "openapi.json"
OUT_FILE = DOCS_ROOT / "reference" / "capability-map.mdx"
DOCS_JSON = DOCS_ROOT / "docs.json"

sys.path.insert(0, str(SCRIPT_DIR))
from registry import load_registry  # noqa: E402

MONOREPO_TREE = "https://github.com/tai42ai/tai42/tree/main"
# The top-level module prefix -> monorepo member path, for the source anchor. A
# module outside this map renders as a plain inline-code path (still a source
# reference, just not a monorepo hyperlink).
CORE_MEMBERS: dict[str, str] = {
    "tai42_kit": "core/kit",
    "tai42_skeleton": "core/skeleton",
    "tai42_contract": "core/contract",
}
# Every HTTP operation is projected from the skeleton operations package.
OPERATIONS_URL = f"{MONOREPO_TREE}/core/skeleton/src/tai42_skeleton/operations"

# Fixed source -> doc-page map (no authored prose; just where the detail lives).
DOC_HTTP_API = "/reference/api"
DOC_SETTINGS = "/reference/settings"
DOC_AGENTS = "/concepts/agents"
DOC_EXTENSIONS = "/concepts/tools-and-extensions"

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


class MapError(RuntimeError):
    """A loud generation failure — exit nonzero, write nothing."""


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("{", "&#123;").replace("}", "&#125;")


def _anchor(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _titleize(name: str) -> str:
    """A display label from an identifier: underscores/hyphens AND camel-case
    boundaries become word breaks, each word capitalized (its interior kept as
    written, so "ContextOverflow" reads "Context Overflow", not the ``.title()``
    mangling "Contextoverflow"). Deterministic and purely name-derived."""
    import re

    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name.replace("_", " ").replace("-", " "))
    return " ".join(word[:1].upper() + word[1:] for word in spaced.split())


def source_cell(module: str | None) -> str:
    """A source-module anchor: a monorepo hyperlink for a core module, else code."""
    if not module:
        return "—"
    top = module.split(".", 1)[0]
    member = CORE_MEMBERS.get(top)
    if member:
        return f"[`{_cell(module)}`]({MONOREPO_TREE}/{member})"
    return f"`{_cell(module)}`"


# --------------------------------------------------------------------------- #
# Areas (pure — fixture-testable)
# --------------------------------------------------------------------------- #


def render_http_api(openapi: dict) -> list[str]:
    paths = openapi.get("paths") or {}
    by_tag: dict[str, list[tuple[str, str, str]]] = {}
    for path in sorted(paths):
        methods = paths[path]
        for method in _HTTP_METHODS:
            op = methods.get(method)
            if not isinstance(op, dict):
                continue
            summary = op.get("summary")
            if not summary:
                raise MapError(f"operation {method.upper()} {path} has no summary — first-party docstring hygiene")
            tag = (op.get("tags") or ["untagged"])[0]
            by_tag.setdefault(tag, []).append((f"{method.upper()} {path}", summary, path))

    lines = ["## HTTP API", ""]
    for tag in sorted(by_tag):
        lines += [
            f"### {_cell(_titleize(tag))}",
            "",
            "| Operation | What it does | Docs | Source |",
            "|---|---|---|---|",
        ]
        for cap, summary, _ in sorted(by_tag[tag]):
            lines.append(
                f"| `{_cell(cap)}` | {_cell(summary)} | [API]({DOC_HTTP_API}) | [operations]({OPERATIONS_URL}) |"
            )
        lines.append("")
    return lines


def render_plugins(listings: list[dict]) -> list[str]:
    lines = ["## Plugins", "", "| Item | What it provides | Docs | Source |", "|---|---|---|---|"]
    for listing in sorted(listings, key=lambda x: (x["namespace"], x["name"])):
        doc = f"/plugins/{listing['namespace']}/{listing['name']}"
        for item in listing["items"]:
            lines.append(
                f"| `{_cell(item['name'])}` | {_cell(item['description'])} | "
                f"[{_cell(listing['name'])}]({doc}) | {source_cell(item.get('module'))} |"
            )
    lines.append("")
    return lines


def render_settings(groups: list[dict]) -> list[str]:
    lines = ["## Settings", "", "| Group | What it configures | Docs | Source |", "|---|---|---|---|"]
    for group in sorted(groups, key=lambda g: g["name"]):
        titled = _titleize(group["name"])
        # The registry name often already carries a "Settings" suffix; don't double it.
        base = titled if titled.lower().endswith("settings") else f"{titled} settings"
        label = f"{base} ({group['module']})"
        doc = f"{DOC_SETTINGS}#{_anchor(group['name'])}"
        lines.append(
            f"| `{_cell(group['name'])}` | {_cell(label)} | [Settings]({doc}) | {source_cell(group['module'])} |"
        )
    lines.append("")
    return lines


def render_agents_extensions(agents: list[dict], extensions: list[dict]) -> list[str]:
    lines = ["## Agents & extensions", ""]
    if not agents and not extensions:
        lines += ["No agents or extensions are registered in the base runtime; agent- and", ""]
        lines += ["extension-kind capabilities are listed under Plugins above.", ""]
        return lines
    lines += ["| Capability | What it does | Docs | Source |", "|---|---|---|---|"]
    for agent in sorted(agents, key=lambda a: a["name"]):
        lines.append(
            f"| `{_cell(agent['name'])}` | {_cell(agent.get('description', ''))} | [Agents]({DOC_AGENTS}) | — |"
        )
    for ext in sorted(extensions, key=lambda e: e["name"]):
        label = f"{_titleize(ext['name'])} ({ext['kind']})"
        lines.append(f"| `{_cell(ext['name'])}` | {_cell(label)} | [Extensions]({DOC_EXTENSIONS}) | — |")
    lines.append("")
    return lines


def render(
    openapi: dict, listings: list[dict], settings_groups: list[dict], agents: list[dict], extensions: list[dict]
) -> str:
    lines = [
        "---",
        'title: "Capability map"',
        'description: "A code-anchored index of every platform capability — HTTP API operations, '
        "listed plugins, settings groups, and agents & extensions — each linked to its docs page and "
        'its source in the public monorepo."',
        'icon: "compass"',
        "---",
        "",
        "{/* GENERATED by scripts/gen_capability_map.py — do not edit. */}",
        "",
        "Every capability the platform exposes, one row apiece, linked to its documentation "
        "and its source. Feature areas are fixed; rows are derived from machine-readable "
        "sources (the generated OpenAPI, the plugin registry, the settings registry, and the "
        "agent/extension registrations), never authored by hand.",
        "",
    ]
    lines += render_http_api(openapi)
    lines += render_plugins(listings)
    lines += render_settings(settings_groups)
    lines += render_agents_extensions(agents, extensions)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Source resolution
# --------------------------------------------------------------------------- #


def load_openapi() -> dict:
    if not OPENAPI.is_file():
        raise MapError(f"{OPENAPI} is absent — run gen_openapi.py first")
    try:
        return json.loads(OPENAPI.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MapError(f"{OPENAPI} is not valid JSON: {exc}") from exc


def load_settings_groups() -> list[dict]:
    """Every registered settings group, offline — the same registry the settings
    reference reads (importing the API surface registers the classes)."""
    try:
        from tai42_kit.settings import registered_settings
        from tai42_skeleton.app.route_registry import load_api_routes
    except ImportError as exc:
        raise MapError(f"tai42_skeleton/tai42_kit not importable ({exc}); run in the skeleton env") from exc
    load_api_routes()
    return [{"name": info.name, "module": info.module} for info in registered_settings()]


def load_agents_extensions() -> tuple[list[dict], list[dict]]:
    """The registered agents/extensions from the live process app.

    A bare regen env with no skeleton on the path has no registry to read, so the
    area renders empty (the ImportError below is the ONLY silenced condition).
    Otherwise the app is built and its live registries are read verbatim: a
    skeleton-present env with nothing registered returns ``([], [])`` naturally
    (both facets empty), and ANY failure reaching the app or a facet is a LOUD
    ``MapError`` naming it — never a silently-empty area."""
    try:
        from tai42_skeleton.app import instance
    except ImportError:
        return [], []
    try:
        app = instance.app
        agents = [
            {"name": name, "description": agent.tool_description} for name, agent in app.agents.all_agents().items()
        ]
        extensions = list(app.extensions.available_extensions())
    except Exception as exc:
        raise MapError(f"agents/extensions registry unavailable from the skeleton app: {exc}") from exc
    return agents, extensions


def update_nav() -> None:
    """Ensure the Reference > Capability map group points at the generated page."""
    data = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    group = {"group": "Capability map", "icon": "compass", "pages": ["reference/capability-map"]}
    for tab in data["navigation"]["tabs"]:
        if tab.get("tab") != "Reference":
            continue
        groups = tab["groups"]
        for existing in groups:
            if existing.get("group") == "Capability map":
                existing["pages"] = group["pages"]
                _write_nav(data)
                return
        insert_at = len(groups)
        for i, existing in enumerate(groups):
            if existing.get("group") == "Settings":
                insert_at = i + 1
                break
        groups.insert(insert_at, group)
        _write_nav(data)
        return
    raise MapError("docs.json: Reference tab not found")


def _write_nav(data: dict) -> None:
    DOCS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    try:
        openapi = load_openapi()
        listings = load_registry()
        settings_groups = load_settings_groups()
        agents, extensions = load_agents_extensions()
        page = render(openapi, listings, settings_groups, agents, extensions)
    except MapError as exc:
        print(f"gen_capability_map: {exc}", file=sys.stderr)
        return 1

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(page, encoding="utf-8")
    update_nav()
    print(f"gen_capability_map: wrote {OUT_FILE.relative_to(DOCS_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
