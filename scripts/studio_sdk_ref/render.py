"""Render a symbol/section to MDX.

Text helpers (prose escaping, frontmatter, comment rendering), signature and
table builders, and the per-symbol section renderer. ``render_symbol`` dispatches
by TypeDoc kind to a per-kind renderer, then appends the shared "Related:"
cross-link block, so every generated section keeps its heading, signature block,
table, and cross-links.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from studio_sdk_ref import config
from studio_sdk_ref.typestr import _param_str, _type_params_str, collect_refs, type_str


def anchor_for(name: str) -> str:
    """A GitHub/Mintlify-style heading anchor for a symbol name."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9 _-]", "", slug)
    return slug.replace(" ", "-")


# --------------------------------------------------------------------------- #
# MDX text helpers
# --------------------------------------------------------------------------- #

_CODE_SPAN = re.compile(r"`[^`]*`")


def _escape_segment(seg: str) -> str:
    return seg.replace("{", "&#123;").replace("}", "&#125;").replace("<", "&lt;").replace(">", "&gt;")


def mdx_escape_prose(text: str) -> str:
    """Escape MDX-hostile characters in prose while leaving inline-code spans
    (single-backtick) untouched, so annotations survive verbatim but stray
    ``{`` / ``<`` in narrative cannot break the MDX parser."""
    out: list[str] = []
    last = 0
    for match in _CODE_SPAN.finditer(text):
        out.append(_escape_segment(text[last : match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(_escape_segment(text[last:]))
    return "".join(out)


def _yaml_dq(value: str) -> str:
    """Escape a value for a double-quoted YAML scalar (backslash and quote)."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def frontmatter(title: str, description: str, icon: str) -> str:
    return f'---\ntitle: "{_yaml_dq(title)}"\ndescription: "{_yaml_dq(description)}"\nicon: "{_yaml_dq(icon)}"\n---\n'


def render_comment(comment: dict | None, id_index: dict[int, dict]) -> str:
    """Render a TypeDoc comment's summary parts to Markdown prose.

    Parts: ``text`` (verbatim prose), ``code`` (already backtick-wrapped), and
    ``inline-tag`` (``{@link X}`` — rendered as the target name in backticks)."""
    if not comment:
        return ""
    parts: list[str] = []
    for part in comment.get("summary", []) or []:
        kind = part.get("kind")
        text = part.get("text", "")
        if kind == "code":
            parts.append(text)  # already includes backticks
        elif kind == "inline-tag":
            target = part.get("target")
            name = text
            if isinstance(target, int) and target in id_index:
                name = id_index[target].get("name", text)
            parts.append(f"`{name}`")
        else:
            parts.append(text)
    return "".join(parts).strip()


def render_comment_text(comment: dict | None) -> str:
    """Plain summary text of a comment (no id_index needed for table cells)."""
    if not comment:
        return ""
    parts = [part.get("text", "") for part in comment.get("summary", []) or []]
    return "".join(parts).strip()


# --------------------------------------------------------------------------- #
# Signature + table rendering
# --------------------------------------------------------------------------- #


def _table_code(value: str) -> str:
    """A backtick code cell safe inside a Markdown table: literal pipes are
    escaped so they don't split columns."""
    return "`" + value.replace("|", "\\|") + "`"


def _table_text(text: str) -> str:
    return mdx_escape_prose(text.replace("\n", " ")).replace("|", "\\|")


def function_signature(refl: dict, name: str) -> tuple[str, dict]:
    """Return (signature_code, primary_signature)."""
    sig = (refl.get("signatures") or [{}])[0]
    params = ", ".join(_param_str(p) for p in sig.get("parameters", []) or [])
    is_async = "async " if (refl.get("flags") or {}).get("isAsync") else ""
    tparams = _type_params_str(sig)
    ret = type_str(sig.get("type"))
    one_line = f"{is_async}function {name}{tparams}({params}): {ret}"
    if len(one_line) <= 92 or not sig.get("parameters"):
        return one_line, sig
    body = ",\n  ".join(_param_str(p) for p in sig.get("parameters"))
    return f"{is_async}function {name}{tparams}(\n  {body},\n): {ret}", sig


def _props_interface(sig: dict, id_index: dict[int, dict]) -> dict | None:
    """When a component takes a single destructured props param whose type is a
    reference to a documented interface, return that interface for a props table."""
    params = sig.get("parameters") or []
    if len(params) != 1:
        return None
    ptype = params[0].get("type") or {}
    if ptype.get("type") != "reference":
        return None
    target = ptype.get("target")
    if not isinstance(target, int):
        return None
    iface = id_index.get(target)
    if iface and iface.get("kind") == config.KIND_INTERFACE:
        return iface
    return None


def render_params_table(sig: dict) -> str:
    rows = []
    for p in sig.get("parameters", []) or []:
        name = p.get("name", "")
        if name == "__namedParameters":
            name = "props"
        typ = _table_code(type_str(p.get("type")))
        default = p.get("defaultValue")
        default_cell = _table_code(str(default)) if default is not None else "—"
        optional = " *(optional)*" if (p.get("flags") or {}).get("isOptional") else ""
        desc = _table_text(render_comment_text(p.get("comment"))) or "—"
        rows.append(f"| `{name}`{optional} | {typ} | {default_cell} | {desc} |")
    if not rows:
        return ""
    header = "| Parameter | Type | Default | Description |\n|---|---|---|---|\n"
    return "**Parameters**\n\n" + header + "\n".join(rows) + "\n"


def render_members_table(iface: dict, heading: str) -> str:
    """Render an interface's / object's members as a table. Methods render their
    call signature in the Type column."""
    rows = []
    for member in sorted(iface.get("children", []) or [], key=lambda m: m.get("name", "")):
        name = member.get("name", "")
        if name.startswith("_"):
            continue
        optional = "?" if (member.get("flags") or {}).get("isOptional") else ""
        if member.get("kind") == config.KIND_METHOD:
            sig = (member.get("signatures") or [{}])[0]
            params = ", ".join(_param_str(p) for p in sig.get("parameters", []) or [])
            type_text = f"{_type_params_str(sig)}({params}) => {type_str(sig.get('type'))}"
            desc = _table_text(render_comment_text(sig.get("comment")))
        else:
            type_text = type_str(member.get("type"))
            desc = _table_text(render_comment_text(member.get("comment")))
        rows.append(f"| `{name}{optional}` | {_table_code(type_text)} | {desc or '—'} |")
    if not rows:
        return ""
    header = f"| {heading} | Type | Description |\n|---|---|---|\n"
    return header + "\n".join(rows) + "\n"


# --------------------------------------------------------------------------- #
# Per-symbol section rendering, dispatched by the reflection's kind.
# --------------------------------------------------------------------------- #


def _render_function_symbol(refl: dict, name: str, id_index: dict[int, dict]) -> tuple[list[str], set[str]]:
    refs: set[str] = set()
    parts: list[str] = []
    signature, sig = function_signature(refl, name)
    summary = render_comment(sig.get("comment") or refl.get("comment"), id_index)
    props_iface = _props_interface(sig, id_index)
    for p in sig.get("parameters", []) or []:
        collect_refs(p.get("type"), refs)
    collect_refs(sig.get("type"), refs)
    if props_iface is not None:
        # A React component: document its props inline from the props interface.
        table = "**Props**\n\n" + render_members_table(props_iface, "Prop")
        refs.add(props_iface["name"])
    else:
        table = render_params_table(sig)
    parts.append(f"```ts\n{signature}\n```\n")
    if summary:
        parts.append(mdx_escape_prose(summary) + "\n")
    if table:
        parts.append(table)
    return parts, refs


def _render_interface_symbol(refl: dict, name: str, id_index: dict[int, dict]) -> tuple[list[str], set[str]]:
    refs: set[str] = set()
    parts: list[str] = []
    extended = refl.get("extendedTypes") or []
    base = ""
    if extended:
        base = " extends " + ", ".join(type_str(b) for b in extended)
        for b in extended:
            collect_refs(b, refs)
    signature = f"interface {name}{_type_params_str(refl)}{base}"
    summary = render_comment(refl.get("comment"), id_index)
    for member in refl.get("children", []) or []:
        collect_refs(member.get("type"), refs)
        for msig in member.get("signatures", []) or []:
            for p in msig.get("parameters", []) or []:
                collect_refs(p.get("type"), refs)
            collect_refs(msig.get("type"), refs)
    table = render_members_table(refl, "Property")
    parts.append(f"```ts\n{signature}\n```\n")
    if summary:
        parts.append(mdx_escape_prose(summary) + "\n")
    if table:
        parts.append("**Properties**\n\n" + table)
    return parts, refs


def _render_type_alias_symbol(refl: dict, name: str, id_index: dict[int, dict]) -> tuple[list[str], set[str]]:
    refs: set[str] = set()
    parts: list[str] = []
    collect_refs(refl.get("type"), refs)
    signature = f"type {name}{_type_params_str(refl)} = {type_str(refl.get('type'))}"
    summary = render_comment(refl.get("comment"), id_index)
    parts.append(f"```ts\n{signature}\n```\n")
    if summary:
        parts.append(mdx_escape_prose(summary) + "\n")
    # A type alias for an object literal renders its fields as a table too.
    decl = (refl.get("type") or {}).get("declaration")
    if isinstance(decl, dict) and decl.get("children"):
        table = render_members_table(decl, "Property")
        if table:
            parts.append("**Properties**\n\n" + table)
    return parts, refs


def _render_variable_symbol(refl: dict, name: str, id_index: dict[int, dict]) -> tuple[list[str], set[str]]:
    refs: set[str] = set()
    parts: list[str] = []
    collect_refs(refl.get("type"), refs)
    const = "const " if (refl.get("flags") or {}).get("isConst") else "let "
    annotated = type_str(refl.get("type"))
    signature = f"{const}{name}: {annotated}"
    summary = render_comment(refl.get("comment"), id_index)
    parts.append(f"```ts\n{signature}\n```\n")
    if summary:
        parts.append(mdx_escape_prose(summary) + "\n")
    return parts, refs


def _render_enum_symbol(refl: dict, name: str, id_index: dict[int, dict]) -> tuple[list[str], set[str]]:
    refs: set[str] = set()
    parts: list[str] = []
    signature = f"enum {name}"
    summary = render_comment(refl.get("comment"), id_index)
    parts.append(f"```ts\n{signature}\n```\n")
    if summary:
        parts.append(mdx_escape_prose(summary) + "\n")
    rows = [
        f"| `{member.get('name')}` | {_table_code(type_str(member.get('type')))} | "
        f"{_table_text(render_comment_text(member.get('comment'))) or '—'} |"
        for member in refl.get("children", []) or []
    ]
    if rows:
        table = "**Members**\n\n| Member | Value | Description |\n|---|---|---|\n" + "\n".join(rows) + "\n"
        parts.append(table)
    return parts, refs


def _render_other_symbol(refl: dict, name: str, id_index: dict[int, dict]) -> tuple[list[str], set[str]]:
    # Any other exported kind: at minimum a signature line so it is never dropped.
    refs: set[str] = set()
    parts: list[str] = []
    signature = f"{name}"
    summary = render_comment(refl.get("comment"), id_index)
    parts.append(f"```ts\n{signature}\n```\n")
    if summary:
        parts.append(mdx_escape_prose(summary) + "\n")
    return parts, refs


_SYMBOL_RENDERERS: dict[int, Callable[[dict, str, dict[int, dict]], tuple[list[str], set[str]]]] = {
    config.KIND_FUNCTION: _render_function_symbol,
    config.KIND_INTERFACE: _render_interface_symbol,
    config.KIND_TYPE_ALIAS: _render_type_alias_symbol,
    config.KIND_VARIABLE: _render_variable_symbol,
    config.KIND_ENUM: _render_enum_symbol,
}


def render_symbol(
    refl: dict,
    id_index: dict[int, dict],
    location: dict[str, tuple[str, str]],
) -> str:
    name = refl["name"]
    handler = _SYMBOL_RENDERERS.get(refl.get("kind"), _render_other_symbol)
    body_parts, refs = handler(refl, name, id_index)
    parts: list[str] = [f"## {name}\n", *body_parts]

    # Cross-links to related, locally documented types.
    related = sorted(n for n in refs if n != name and n in location)
    if related:
        links = ", ".join(f"[{n}](/{config.NAV_PREFIX}/{location[n][0]}#{location[n][1]})" for n in related)
        parts.append(f"**Related:** {links}\n")

    return "\n".join(parts) + "\n"
