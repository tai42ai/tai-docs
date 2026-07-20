#!/usr/bin/env python3
"""Generate the ecosystem catalog reference from the packaged ``ecosystem.yml``.

The single input is the STATIC data file shipped inside the installed
``tai_skeleton`` package (``tai_skeleton/data/ecosystem.yml``). This script
reads it offline with ZERO plugin imports and renders the catalog page under
``reference/catalog/``.

Each entry carries ``{name, kind, group, package, module, description}`` and NO
``repo`` field. The repo column is derived at render time by joining each
entry's ``package`` against the ``packages`` mapping in the SAME file, so the
repo lives in one place and is never duplicated per entry. A ``package`` absent
from that mapping is a LOUD error — the script exits non-zero and writes
nothing, never a blank repo cell.

Run it where ``tai_skeleton`` resolves (the tai-skeleton virtualenv)::

    cd tai-skeleton && uv run python ../tai-docs/scripts/gen_catalog.py
"""

from __future__ import annotations

import json
import sys
from importlib import resources
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    print(f"gen_catalog: PyYAML is not importable: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
OUT_DIR = DOCS_ROOT / "reference" / "catalog"
DOCS_JSON = DOCS_ROOT / "docs.json"

# Human-facing ordering + labels for the kind sections. Any kind seen in the
# data that is not listed here is still rendered (appended under its raw name),
# so a new kind can never be silently dropped.
KIND_ORDER = [
    ("tool", "Tools"),
    ("extension", "Extensions"),
    ("agent", "Agents"),
    ("connector", "Connectors"),
    ("webhook-verifier", "Webhook verifiers"),
    ("channel", "Channels"),
    ("backend", "Backends"),
    ("storage", "Storage providers"),
    ("monitoring", "Monitoring backends"),
    ("accounts", "Accounts providers"),
    ("identity", "Identity providers"),
    ("config", "Config providers"),
]

_ENTRY_FIELDS = ("name", "kind", "group", "package", "module", "description")

# Icon per kind for the jump-to CardGroup at the top of the page. An unlisted
# kind falls back to the section's generic table icon.
KIND_ICONS = {
    "tool": "wrench",
    "extension": "puzzle-piece",
    "agent": "robot",
    "connector": "plug",
    "webhook-verifier": "bolt",
    "channel": "paper-plane",
    "backend": "server",
    "storage": "database",
    "monitoring": "chart-line",
    "accounts": "user-lock",
    "identity": "id-card",
    "config": "gear",
}


def _anchor(heading: str) -> str:
    """The Mintlify anchor slug for a Markdown heading."""
    return heading.lower().replace(" ", "-")


def load_ecosystem() -> dict:
    """Read the packaged ecosystem.yml from the installed tai_skeleton package."""
    try:
        data_file = resources.files("tai_skeleton").joinpath("data/ecosystem.yml")
        raw = data_file.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, AttributeError) as exc:
        print(f"gen_catalog: cannot locate packaged ecosystem.yml: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    doc = yaml.safe_load(raw)
    if not isinstance(doc, dict):
        print("gen_catalog: ecosystem.yml is not a mapping", file=sys.stderr)
        raise SystemExit(1)
    return doc


def mdx_cell(text: str) -> str:
    """Escape a value for safe inclusion in an MDX table cell."""
    return (
        str(text)
        .replace("|", "\\|")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render(doc: dict) -> str:
    entries = doc.get("entries")
    packages = doc.get("packages")

    if not entries:
        print("gen_catalog: ecosystem.yml has no entries", file=sys.stderr)
        raise SystemExit(1)
    if not isinstance(packages, dict) or not packages:
        print("gen_catalog: ecosystem.yml has no packages mapping", file=sys.stderr)
        raise SystemExit(1)

    # Validate + join every row against the package->repo mapping BEFORE
    # rendering, so a single unmapped package fails the whole run loudly.
    normalized: list[dict] = []
    for i, entry in enumerate(entries):
        missing = [f for f in _ENTRY_FIELDS if f not in entry]
        if missing:
            print(
                f"gen_catalog: entry #{i} ({entry.get('name', '?')}) missing fields: {', '.join(missing)}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        pkg = entry["package"]
        if pkg not in packages:
            print(
                f"gen_catalog: package '{pkg}' (entry '{entry['name']}') is not "
                f"in the packages mapping — cannot resolve its repo",
                file=sys.stderr,
            )
            raise SystemExit(1)
        row = dict(entry)
        row["repo"] = packages[pkg]
        normalized.append(row)

    # Group rows by kind in the pinned order; append any unknown kinds last.
    by_kind: dict[str, list[dict]] = {}
    for row in normalized:
        by_kind.setdefault(row["kind"], []).append(row)

    ordered_kinds = [k for k, _ in KIND_ORDER if k in by_kind]
    ordered_kinds += [k for k in by_kind if k not in {k for k, _ in KIND_ORDER}]
    labels = dict(KIND_ORDER)

    lines: list[str] = [
        "---",
        'title: "Ecosystem catalog"',
        'description: "Every shipped tool, extension, agent, connector, and provider in the tai ecosystem."',
        'icon: "table-list"',
        "---",
        "",
        f"The catalog lists every registration shipped across the ecosystem — "
        f"{len(normalized)} entries across {len(ordered_kinds)} kinds. Each row's "
        "repository is the package's home; follow it for that implementation's "
        "own documentation.",
        "",
    ]

    # Jump-to CardGroup, one card per kind section, for parity with the
    # narrative section indexes. Each card links to its heading anchor below.
    lines.append("<CardGroup cols={2}>")
    for kind in ordered_kinds:
        heading = labels.get(kind, kind)
        count = len(by_kind[kind])
        icon = KIND_ICONS.get(kind, "table-list")
        lines.append(f'  <Card title="{heading}" icon="{icon}" href="/reference/catalog#{_anchor(heading)}">')
        lines.append(f"    {count} {'entry' if count == 1 else 'entries'}.")
        lines.append("  </Card>")
    lines.append("</CardGroup>")
    lines.append("")

    for kind in ordered_kinds:
        rows = by_kind[kind]
        heading = labels.get(kind, kind)
        lines.append(f"## {heading}")
        lines.append("")
        lines.append("| Name | Group | Package | Repo | Description |")
        lines.append("|---|---|---|---|---|")
        for row in sorted(rows, key=lambda r: (r["group"], r["name"])):
            lines.append(
                "| `{name}` | {group} | `{package}` | {repo} | {desc} |".format(
                    name=mdx_cell(row["name"]),
                    group=mdx_cell(row["group"]),
                    package=mdx_cell(row["package"]),
                    repo=mdx_cell(row["repo"]),
                    desc=mdx_cell(row["description"]),
                )
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def update_nav() -> None:
    """Ensure the Reference > Catalog group points at the generated page."""
    data = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    for tab in data["navigation"]["tabs"]:
        if tab.get("tab") != "Reference":
            continue
        for group in tab["groups"]:
            if group.get("group") == "Catalog":
                group["pages"] = ["reference/catalog/index"]
                # ensure_ascii=False so hand-authored non-ASCII in docs.json
                # (e.g. em-dashes) survives a partial regen byte-for-byte and
                # never re-encodes to \\uXXXX escapes -- matches gen_cli.
                DOCS_JSON.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                return
    raise RuntimeError("docs.json: Reference > Catalog group not found")


def main() -> int:
    doc = load_ecosystem()
    page = render(doc)  # raises SystemExit(1) on any unresolved package

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.mdx").write_text(page, encoding="utf-8")
    update_nav()

    entries = doc["entries"]
    print(f"gen_catalog: wrote {OUT_DIR / 'index.mdx'} ({len(entries)} entries, all packages resolved to a repo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
