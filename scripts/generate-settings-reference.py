#!/usr/bin/env python3
"""Generate the settings / env-var reference from the registered settings groups.

The data source is the SAME settings registry the ``GET /api/config/settings-schema``
route reports and that ``tai config lint`` validates offline: importing the API
surface with :func:`load_api_routes` registers every kit + skeleton (and
manifest-loaded plugin) settings class, and :func:`registered_settings` then
yields each group with its field metadata. This runs entirely OFFLINE with no
server, no manifest, and no auth — matching the other reference generators, which
introspect the installed ``tai_skeleton`` package rather than calling a live
server.

Only the field DEFAULT is rendered, never a resolved runtime value: the schema
route resolves each field against ``os.environ`` and the stored env override and
so can carry real secret values, which must never land in committed docs. The
default is the code-level default and is safe to publish; a secret field that
nonetheless ships a non-empty default is a LOUD error (it exits non-zero and
writes nothing) rather than being published.

Run it where ``tai_skeleton`` resolves (the tai-skeleton virtualenv)::

    cd tai-skeleton && uv run python ../tai-docs/scripts/generate-settings-reference.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

try:
    from tai_kit.settings import registered_settings
    from tai_skeleton.app.route_registry import load_api_routes
except ImportError as exc:  # pragma: no cover - environment guard
    print(
        f"generate-settings-reference: the tai_skeleton/tai_kit packages are not "
        f"importable ({exc}); run inside the tai-skeleton virtualenv.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent

# Defaults derived from ``tempfile.gettempdir()`` resolve to a machine-specific
# path (``/var/folders/...`` on macOS, ``/tmp`` on Linux). The published page is
# a committed artifact checked for drift, so such defaults are rendered in the
# canonical POSIX form the deployment targets use.
_LOCAL_TMP_DIR = tempfile.gettempdir()
_CANONICAL_TMP_DIR = "/tmp"
OUT_FILE = DOCS_ROOT / "reference" / "settings.mdx"
DOCS_JSON = DOCS_ROOT / "docs.json"

# The Reference-tab nav group this page lives in. The generator owns this group
# the way gen_catalog owns "Catalog": it is created after the "CLI" group when
# absent, and its single page is (re)pinned on every run.
NAV_GROUP = "Settings"
NAV_GROUP_ICON = "sliders"
NAV_PAGE = "reference/settings"
NAV_INSERT_AFTER = "CLI"


def _anchor(heading: str) -> str:
    """The Mintlify anchor slug for a Markdown heading."""
    return heading.lower().replace(" ", "-")


def load_groups() -> list[dict]:
    """Every registered settings group with its field metadata, offline.

    Importing the API surface registers the kit + skeleton settings classes —
    the same set ``GET /api/config/settings-schema`` reports — without booting a
    server. Each field is dumped to the plain metadata mapping the route emits
    (``name``, ``env_var``, ``type``, ``default``, ``required``, ``secret``,
    ``description``, ``nested_group``); the resolved per-request ``value`` the
    route adds is deliberately NOT included, so no runtime value is published.
    """
    load_api_routes()
    groups: list[dict] = []
    for cls_info in registered_settings():
        groups.append(
            {
                "name": cls_info.name,
                "module": cls_info.module,
                "qualname": cls_info.qualname,
                "fields": [field.model_dump() for field in cls_info.fields],
            }
        )
    if not groups:
        print(
            "generate-settings-reference: no settings groups registered — the "
            "settings registry is empty, refusing to write an empty reference.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return groups


def audit_secrets(groups: list[dict]) -> None:
    """Fail LOUDLY if any secret field ships a non-empty default.

    Defaults are the only values this page publishes. A code-level default is
    normally ``None``/empty for a secret; a non-empty secret default would leak a
    baked-in credential into committed docs, so it aborts the whole run rather
    than being redacted-and-forgotten.
    """
    offenders: list[str] = []
    for group in groups:
        for field in group["fields"]:
            if field.get("secret") and field.get("default") not in (None, ""):
                offenders.append(f"{group['name']}.{field['name']} (${field.get('env_var')})")
    if offenders:
        print(
            "generate-settings-reference: secret field(s) ship a non-empty default — "
            "refusing to publish a baked-in credential:\n  " + "\n  ".join(offenders),
            file=sys.stderr,
        )
        raise SystemExit(1)


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


def render_default(field: dict) -> str:
    """The Default cell: the code-level default, rendered as inline code.

    ``None`` (an unset optional) renders as an em dash; every other default —
    including ``false``, ``0``, ``""``, ``[]``, and ``{}`` — renders as its JSON
    literal so the empty and the absent cases stay distinct.

    A string default rooted in the running machine's temp directory is
    normalised to the canonical ``/tmp`` form, so the generated page is
    identical whatever platform generates it.
    """
    default = field.get("default")
    if default is None:
        return "—"
    if isinstance(default, str) and default.startswith(_LOCAL_TMP_DIR):
        default = _CANONICAL_TMP_DIR + default[len(_LOCAL_TMP_DIR) :]
    return code_cell(json.dumps(default))


def render_description(field: dict) -> str:
    """The Description cell: the field description plus a Secret / reference note.

    The settings metadata carries no free-text description today, so the cell is
    built from what the schema does expose — a ``Secret.`` marker for masked
    fields and, for a nested-group reference field (empty ``env_var``), a link to
    the nested group's own section below.
    """
    parts: list[str] = []
    description = field.get("description")
    if description:
        parts.append(mdx_cell(description))
    nested = field.get("nested_group")
    if not field.get("env_var") and nested:
        parts.append(f"Grouped settings — see [{mdx_cell(nested)}](#{_anchor(nested)}).")
    if field.get("secret"):
        parts.append("Secret.")
    return " ".join(parts) if parts else "—"


def render_env_var(field: dict) -> str:
    """The Env var cell: the variable name, or an em dash for a reference field."""
    env_var = field.get("env_var")
    if not env_var:
        return "—"
    return code_cell(env_var)


def render(groups: list[dict]) -> str:
    total_fields = sum(len(g["fields"]) for g in groups)
    ordered = sorted(groups, key=lambda g: g["name"])

    lines: list[str] = [
        "---",
        'title: "Settings reference"',
        'description: "Every environment variable the tai server reads, grouped by settings group."',
        'icon: "sliders"',
        "---",
        "",
        "<Note>",
        "  Generated from `tai config settings-schema` — do not edit by hand; regenerate",
        "  with `scripts/generate-settings-reference.py`.",
        "</Note>",
        "",
        f"Every registered settings group and the environment variables it reads — "
        f"{total_fields} variables across {len(ordered)} groups. Each row lists the "
        "variable, its type, its default, and whether it is required. Values shown are "
        "code-level defaults; a running server resolves each variable from the "
        "environment, then any stored override, then this default.",
        "",
    ]

    for group in ordered:
        heading = group["name"]
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(f"Module `{group['module']}`.")
        lines.append("")
        lines.append("| Env var | Type | Default | Required | Description |")
        lines.append("|---|---|---|---|---|")
        for field in group["fields"]:
            required = "Required" if field.get("required") else "Optional"
            type_cell = code_cell(field["type"]) if field.get("type") else "—"
            cells = (
                render_env_var(field),
                type_cell,
                render_default(field),
                required,
                render_description(field),
            )
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    return "\n".join(lines) + "\n"


def update_nav() -> None:
    """Ensure the Reference > Settings group points at the generated page.

    Idempotent: an existing ``Settings`` group has its pages re-pinned; an absent
    one is inserted immediately after the ``CLI`` group. A missing Reference tab
    is a LOUD error.
    """
    data = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    for tab in data["navigation"]["tabs"]:
        if tab.get("tab") != "Reference":
            continue
        groups = tab["groups"]
        for group in groups:
            if group.get("group") == NAV_GROUP:
                group["pages"] = [NAV_PAGE]
                _write_nav(data)
                return
        insert_at = len(groups)
        for i, group in enumerate(groups):
            if group.get("group") == NAV_INSERT_AFTER:
                insert_at = i + 1
                break
        groups.insert(insert_at, {"group": NAV_GROUP, "icon": NAV_GROUP_ICON, "pages": [NAV_PAGE]})
        _write_nav(data)
        return
    raise RuntimeError("docs.json: Reference tab not found")


def _write_nav(data: dict) -> None:
    # ensure_ascii=False so hand-authored non-ASCII in docs.json (em dashes)
    # survives a regen byte-for-byte instead of re-encoding to \\uXXXX escapes —
    # matches gen_catalog / gen_cli.
    DOCS_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    groups = load_groups()
    audit_secrets(groups)  # raises SystemExit(1) on a baked-in credential
    page = render(groups)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(page, encoding="utf-8")
    update_nav()

    total_fields = sum(len(g["fields"]) for g in groups)
    print(
        f"generate-settings-reference: wrote {OUT_FILE.relative_to(DOCS_ROOT)} "
        f"({len(groups)} groups, {total_fields} variables)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
