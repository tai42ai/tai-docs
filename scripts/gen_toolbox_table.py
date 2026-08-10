#!/usr/bin/env python3
"""Generate the standard-toolbox summary table in ``guides/standard-toolbox.mdx``.

The "standard toolbox" is the batteries-included default set shipped in the
``tai42-toolbox`` package. Its tool and extension registrations live in the
committed ``plugins/_registry.json`` (the marketplace snapshot ``gen_plugins.py``
emits). This script filters that data to the toolbox's tools and extensions and
rewrites ONLY the generated table between two stable markers in the guide,
leaving the hand-written prose untouched. The table therefore rides the drift
gate and is never hand-maintained.

Offline: reads the committed registry snapshot, no network::

    python3 scripts/gen_toolbox_table.py

Fail-loud contract: if the registry cannot be read, has no matching toolbox
entries, or the guide is missing its markers, this exits non-zero and writes
nothing -- it never leaves a blank or partial table.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
GUIDE = DOCS_ROOT / "guides" / "standard-toolbox.mdx"
sys.path.insert(0, str(SCRIPT_DIR))

from registry import load_registry  # noqa: E402

# The package whose tools/extensions ARE the standard toolbox.
TOOLBOX_PACKAGE = "tai42-toolbox"
# Only these kinds appear in the table (tools and their clip-on extensions).
TOOLBOX_KINDS = ("tool", "extension")

START_MARKER = "{/* GENERATED:toolbox-table START */}"
END_MARKER = "{/* GENERATED:toolbox-table END */}"

# Human labels for the kind column, in stable section order.
KIND_LABELS = {"tool": "Tool", "extension": "Extension"}
_KIND_RANK = {kind: i for i, kind in enumerate(TOOLBOX_KINDS)}


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


def toolbox_rows(listings: list[dict]) -> list[dict]:
    """The toolbox's tool/extension item rows, validated and stably ordered."""
    rows: list[dict] = []
    for listing in listings:
        if listing.get("package") != TOOLBOX_PACKAGE:
            continue
        for item in listing["items"]:
            if item.get("kind") not in TOOLBOX_KINDS:
                continue
            for field in ("name", "kind", "description"):
                if not item.get(field):
                    print(
                        f"gen_toolbox_table: a {TOOLBOX_PACKAGE} item ({item.get('name', '?')}) is missing '{field}'",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)
            rows.append(item)

    if not rows:
        print(
            f"gen_toolbox_table: no '{TOOLBOX_PACKAGE}' tool/extension items in the registry",
            file=sys.stderr,
        )
        raise SystemExit(1)

    rows.sort(key=lambda r: (_KIND_RANK[r["kind"]], r["name"]))
    return rows


def render_table(rows: list[dict]) -> str:
    lines = [
        "| Name | Kind | Summary |",
        "|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| `{name}` | {kind} | {summary} |".format(
                name=mdx_cell(row["name"]),
                kind=mdx_cell(KIND_LABELS.get(row["kind"], row["kind"])),
                summary=mdx_cell(row["description"]),
            )
        )
    return "\n".join(lines)


def inject(guide_text: str, table: str) -> str:
    """Replace the marked block in the guide with the freshly rendered table."""
    if START_MARKER not in guide_text or END_MARKER not in guide_text:
        print(
            f"gen_toolbox_table: {GUIDE.name} is missing the '{START_MARKER}' ... '{END_MARKER}' markers",
            file=sys.stderr,
        )
        raise SystemExit(1)

    start = guide_text.index(START_MARKER)
    # Search unbounded (not from `start`) so a reversed order -- END before START
    # -- is caught by the guard below with a clean diagnostic, rather than
    # .index(END_MARKER, start) raising a bare "substring not found" ValueError.
    end = guide_text.index(END_MARKER)
    if end < start:
        print("gen_toolbox_table: toolbox-table END marker precedes START", file=sys.stderr)
        raise SystemExit(1)

    before = guide_text[:start]
    after = guide_text[end + len(END_MARKER) :]
    block = f"{START_MARKER}\n\n{table}\n\n{END_MARKER}"
    return before + block + after


def main() -> int:
    if not GUIDE.is_file():
        print(f"gen_toolbox_table: guide not found at {GUIDE}", file=sys.stderr)
        return 1

    listings = load_registry()
    rows = toolbox_rows(listings)  # raises SystemExit on a bad/empty registry
    table = render_table(rows)

    guide_text = GUIDE.read_text(encoding="utf-8")
    updated = inject(guide_text, table)  # raises SystemExit if markers absent
    GUIDE.write_text(updated, encoding="utf-8")

    print(f"gen_toolbox_table: wrote {len(rows)} toolbox rows into {GUIDE.relative_to(DOCS_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
