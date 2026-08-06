#!/usr/bin/env python3
"""Generate the DB-backed feature-gate OFF-behavior table in ``concepts/config-and-secrets.mdx``.

Each DB-backed feature (background tool runs, interactions, rate limiting, the
marketplace/tool-metadata/connectors/versioning stores) is a gate whose ``off``
state is the honest answer when no store is configured. Their registration —
kind name, human label, enabling env var, and the one-line uniform-OFF contract —
lives once in the ``tai42_skeleton`` ``_GATED_FEATURES`` registry (the same list
``collect_kind_status`` renders into the live ``GET /api/system/kinds`` table).
This script imports that registry offline and rewrites ONLY the generated table
between two stable markers in the concept page, leaving the hand-written prose
untouched. The table therefore rides the drift gate and never drifts from the
registry.

Run it where ``tai42_skeleton`` resolves (the tai42-skeleton virtualenv)::

    cd tai42/core/skeleton && uv run python ../../../tai-docs/scripts/gen_gated_features.py

Fail-loud contract: if the registry is empty or the concept page is missing its
markers, this exits non-zero and writes nothing -- it never leaves a blank or
partial table.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from tai42_skeleton.app.kind_status import _GATED_FEATURES
except ImportError as exc:  # pragma: no cover - environment guard
    print(
        f"gen_gated_features: the tai42_skeleton package is not importable ({exc}); "
        f"run inside the tai42-skeleton virtualenv.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
PAGE = DOCS_ROOT / "concepts" / "config-and-secrets.mdx"

START_MARKER = "{/* GENERATED:gated-features-table START */}"
END_MARKER = "{/* GENERATED:gated-features-table END */}"


def mdx_cell(text: str) -> str:
    """Escape a value for safe inclusion in a plain-text MDX table cell."""
    return (
        str(text)
        .replace("|", "\\|")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def code_cell(text: str) -> str:
    """Wrap a value in an inline code span for an MDX table cell.

    Inside a code span MDX leaves ``{``/``}``/``<``/``>`` literal, so only the
    table delimiter ``|`` needs escaping.
    """
    return "`" + str(text).replace("|", "\\|") + "`"


def render_table() -> str:
    """The OFF-behavior table, one row per gated feature in registry order.

    The registry is a fixed ordered list, so the output is deterministic. Fails
    LOUDLY on an empty registry rather than emitting a header-only table.
    """
    if not _GATED_FEATURES:
        print("gen_gated_features: the gated-feature registry is empty", file=sys.stderr)
        raise SystemExit(1)

    lines = [
        "| Feature | Enabling variable(s) | OFF behavior | Kinds row |",
        "| --- | --- | --- | --- |",
    ]
    for feature in _GATED_FEATURES:
        lines.append(
            "| {feature} | {var} | {off} | {kinds} |".format(
                feature=mdx_cell(feature.label),
                var=code_cell(feature.enabling_var()),
                off=mdx_cell(feature.off_behavior),
                kinds=f"{code_cell(feature.kind)} reports {code_cell('off')}",
            )
        )
    return "\n".join(lines)


def inject(page_text: str, table: str) -> str:
    """Replace the marked block in the page with the freshly rendered table."""
    if START_MARKER not in page_text or END_MARKER not in page_text:
        print(
            f"gen_gated_features: {PAGE.name} is missing the '{START_MARKER}' ... '{END_MARKER}' markers",
            file=sys.stderr,
        )
        raise SystemExit(1)

    start = page_text.index(START_MARKER)
    # Search unbounded (not from `start`) so a reversed order -- END before START
    # -- is caught by the guard below with a clean diagnostic, rather than
    # .index(END_MARKER, start) raising a bare "substring not found" ValueError.
    end = page_text.index(END_MARKER)
    if end < start:
        print("gen_gated_features: gated-features-table END marker precedes START", file=sys.stderr)
        raise SystemExit(1)

    before = page_text[:start]
    after = page_text[end + len(END_MARKER) :]
    block = f"{START_MARKER}\n\n{table}\n\n{END_MARKER}"
    return before + block + after


def main() -> int:
    if not PAGE.is_file():
        print(f"gen_gated_features: page not found at {PAGE}", file=sys.stderr)
        return 1

    table = render_table()  # raises SystemExit on an empty registry

    page_text = PAGE.read_text(encoding="utf-8")
    updated = inject(page_text, table)  # raises SystemExit if markers absent
    PAGE.write_text(updated, encoding="utf-8")

    print(f"gen_gated_features: wrote {len(_GATED_FEATURES)} gated-feature rows into {PAGE.relative_to(DOCS_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
