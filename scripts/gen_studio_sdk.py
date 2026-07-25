#!/usr/bin/env python3
"""Generate the Studio SDK reference from ``@tai42/studio-sdk`` via TypeDoc.

This script shells out to a PINNED TypeDoc toolchain (owned by tai-docs, under
``scripts/studio_sdk_typedoc/`` — never a tai-studio dependency) to produce a
JSON object model of the package's PUBLIC export surface, then renders that
model into one MDX reference page per category under ``reference/studio-sdk/``.
Doc comments in the source are the source of truth; every rendered symbol traces
to a real export of a real entry point.

Scope pin: only the package's published entry points are documented —
``.`` (``src/index.ts``), ``./host`` (``src/host.ts``), and ``./testing``
(``src/testing.ts``). Internal/unexported symbols are OUT. The generator
enumerates whatever those entry points export at build time; it never carries a
hard-coded symbol list. Symbols are placed into pages by their source directory,
so a newly exported symbol lands in the matching category automatically.

Owned-renderer pattern (mirrors ``gen_sdk.py``): TypeDoc emits an object model,
not MDX; the JSON -> MDX renderer lives here. Every page carries MDX frontmatter
(title/description/icon); every symbol section renders a heading, a signature
code block, a parameters/props table, cross-links to related types, and a stable
anchor.

Fail-loud contract: the script runs TypeDoc, renders every page into memory, and
validates the required-symbol checklist BEFORE touching the output directory. If
TypeDoc cannot run, if it produces no public exports, or if a required symbol is
missing from the rendered output, it exits non-zero and writes NOTHING — it
never overwrites a good reference with an empty or partial one.

Run it from anywhere (paths are resolved relative to this file)::

    python3 tai-docs/scripts/gen_studio_sdk.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
WORKSPACE_ROOT = DOCS_ROOT.parent

STUDIO_SDK_DIR = WORKSPACE_ROOT / "tai-studio" / "packages" / "studio-sdk"
TSCONFIG = STUDIO_SDK_DIR / "tsconfig.build.json"
# The three PUBLISHED entry points (package.json `exports`): `.`, `./host`,
# `./testing`. Paths are relative to STUDIO_SDK_DIR (TypeDoc's cwd).
ENTRY_POINTS = ["src/index.ts", "src/host.ts", "src/testing.ts"]

# Pinned TypeDoc toolchain owned by tai-docs (see studio_sdk_typedoc/package.json).
TYPEDOC_DIR = SCRIPT_DIR / "studio_sdk_typedoc"
TYPEDOC_BIN = TYPEDOC_DIR / "node_modules" / ".bin" / "typedoc"

OUT_DIR = DOCS_ROOT / "reference" / "studio-sdk"
DOCS_JSON = DOCS_ROOT / "docs.json"

NAV_PREFIX = "reference/studio-sdk"


# --------------------------------------------------------------------------- #
# TypeDoc ReflectionKind values (a bit-flag enum; only the ones we render).
# --------------------------------------------------------------------------- #

KIND_PROJECT = 1
KIND_MODULE = 2
KIND_ENUM = 8
KIND_ENUM_MEMBER = 16
KIND_VARIABLE = 32
KIND_FUNCTION = 64
KIND_CLASS = 128
KIND_INTERFACE = 256
KIND_PROPERTY = 1024
KIND_METHOD = 2048
KIND_CALL_SIG = 4096
KIND_TYPE_ALIAS = 2097152


# --------------------------------------------------------------------------- #
# Page specification: each category collects the top-level exports whose source
# lives under the mapped directory. Order is stable so the generated nav and
# anchors do not churn between runs. `dirs` matches the first path segment under
# `src/`; `modules` matches the entry-point module a symbol was exported from.
# The catch-all "utilities" category collects anything unmatched (e.g. a
# re-exported type whose source is outside `src/`), so no export is ever dropped.
# --------------------------------------------------------------------------- #

CATEGORIES: list[dict] = [
    {
        "slug": "plugin-api",
        "title": "Plugin API",
        "description": (
            "The plugin contract a Studio plugin implements — the context, "
            "contribution types, and the compatibility gate."
        ),
        "icon": "plug",
        "dirs": {"plugin"},
        "modules": set(),
    },
    {
        "slug": "hooks",
        "title": "Hooks",
        "description": (
            "The React hooks and providers every feature builds on — API "
            "access, theme, auth, and the interactions stream."
        ),
        "icon": "circle-nodes",
        "dirs": {"hooks"},
        "modules": set(),
    },
    {
        "slug": "navigation",
        "title": "Navigation",
        "description": "The shell⇄feature route-token contract — the navigation provider, links, and resolution hooks.",
        "icon": "compass",
        "dirs": {"navigation"},
        "modules": set(),
    },
    {
        "slug": "components",
        "title": "Components",
        "description": "The design-system components — inputs, layout, tables, pickers, and disclosure primitives.",
        "icon": "shapes",
        "dirs": {"components"},
        "modules": set(),
    },
    {
        "slug": "schema-forms",
        "title": "Schema forms",
        "description": "The schema-driven form renderer and the JSON Schema helpers it is built on.",
        "icon": "list-check",
        "dirs": {"schema-form"},
        "modules": set(),
    },
    {
        "slug": "mcp-widgets",
        "title": "MCP widgets",
        "description": "The MCP-context widgets — elicitation forms and structured-output rendering.",
        "icon": "diagram-project",
        "dirs": {"elicitation", "structured-output"},
        "modules": set(),
    },
    {
        "slug": "utilities",
        "title": "Utilities",
        "description": "Shared helpers and re-exported types the SDK exposes.",
        "icon": "wrench",
        "dirs": set(),  # catch-all fallback
        "modules": set(),
    },
    {
        "slug": "host-testing",
        "title": "Host & testing",
        "description": "The host-only registry API (loadPlugin / getContributions) and the test-only reset.",
        "icon": "shield-halved",
        "dirs": set(),
        "modules": {"host", "testing"},
    },
]

FALLBACK_SLUG = "utilities"

# The load-bearing public exports. Every one MUST appear as a rendered heading or
# the run fails. This is a coverage floor, NOT the documented set — the generator
# documents whatever the entry points export.
REQUIRED_SYMBOLS = [
    "SchemaForm",
    "ToolPicker",
    "ExtensionPicker",
    "ElicitationForm",
    "StructuredOutput",
    "useApi",
    "useTheme",
    "useInteractionsStream",
    "loadPlugin",
    "getContributions",
    "PluginContext",
    "PluginEntry",
    "STUDIO_PLUGIN_API_VERSION",
    "checkPluginApiVersion",
    "__resetContributions",
]

# Required symbols whose section MUST carry a parameters/props table (functions
# with parameters, React components, and interfaces). Zero-argument functions and
# constants legitimately have no table, so they are excluded from this stricter
# check while still being covered by the heading/signature check above.
REQUIRED_WITH_TABLE = [
    "SchemaForm",
    "ToolPicker",
    "ExtensionPicker",
    "ElicitationForm",
    "StructuredOutput",
    "PluginContext",
    "loadPlugin",
    "checkPluginApiVersion",
]


class GenerationError(RuntimeError):
    """Raised when the reference cannot be generated (fail-loud)."""


# --------------------------------------------------------------------------- #
# Named-alias resolution for expanded external types
# --------------------------------------------------------------------------- #
# TypeScript resolves some type aliases away before TypeDoc sees them — notably a
# computed alias like ``ApiClient = ReturnType<typeof createApiClient>`` — so at
# every use site TypeDoc serialises the FULL structural object literal instead of
# the name. That leaks internal impl types, produces multi-thousand-char one-line
# signatures, and hits TypeDoc's depth limit (literal ``...`` ellipses).
#
# We recover the name via TypeDoc's ``symbolIdMap``: both the anonymous inline
# literal and the documented export carry a symbol origin (package + source
# path). When an EXTERNAL source file exports exactly one documented type, an
# anonymous object literal originating from that file IS that type — so we render
# its name (and cross-link it) instead of expanding. Rendering stops at the outer
# literal, so nested member literals from the same file are never reached and
# never mis-named. Set once per ``build_reference`` run; deterministic within it.
_SYMBOL_ID_MAP: dict[str, dict] = {}
_ALIAS_ORIGIN_TO_NAME: dict[tuple[str, str], str] = {}


def _origin_of(decl: dict) -> tuple[str, str] | None:
    """The (packageName, packagePath) symbol origin of a reflection, or None."""
    sid = _SYMBOL_ID_MAP.get(str(decl.get("id")))
    if not sid:
        return None
    pkg = sid.get("packageName")
    path = sid.get("packagePath")
    if pkg is None or path is None:
        return None
    return (pkg, path)


def _collapsed_alias(decl: dict) -> str | None:
    """If ``decl`` is an inline object literal that is really a documented,
    externally-defined named type (TypeDoc expanded it because TypeScript
    resolved the alias away), return that type's NAME; else None."""
    if not decl.get("children"):
        return None
    origin = _origin_of(decl)
    if origin is None:
        return None
    return _ALIAS_ORIGIN_TO_NAME.get(origin)


def _build_alias_origins(exports: list[tuple[dict, str]]) -> dict[tuple[str, str], str]:
    """Map each EXTERNAL source origin that exports exactly one documented type to
    that type's name. Local (``@tai42/studio-sdk``) types already render by
    reference, so they are excluded — only re-exported external types (whose
    aliases TypeDoc expands) need recovering."""
    origin_names: dict[tuple[str, str], set[str]] = {}
    for refl, _module in exports:
        origin = _origin_of(refl)
        if origin is None or origin[0] == "@tai42/studio-sdk":
            continue
        origin_names.setdefault(origin, set()).add(refl["name"])
    return {origin: next(iter(names)) for origin, names in origin_names.items() if len(names) == 1}


def _type_params_str(container: dict | None) -> str:
    """Render a reflection's / signature's ``<T extends C = D, …>`` type-parameter
    list, or "" when there are none. Without this a generic symbol renders a free,
    undeclared ``T`` in its signature."""
    tparams = (container or {}).get("typeParameters") or []
    if not tparams:
        return ""
    parts: list[str] = []
    for tp in tparams:
        text = tp.get("name", "")
        constraint = tp.get("type")
        if constraint:
            text += f" extends {type_str(constraint)}"
        default = tp.get("default")
        if default:
            text += f" = {type_str(default)}"
        parts.append(text)
    return "<" + ", ".join(parts) + ">"


# --------------------------------------------------------------------------- #
# TypeDoc invocation
# --------------------------------------------------------------------------- #


def run_typedoc(entry_points: list[str] | None = None) -> dict:
    """Invoke the pinned TypeDoc against the entry points and return the parsed
    project JSON. Raises GenerationError on any failure — a missing binary, a
    TypeDoc error, or output that is not the expected project object."""
    entry_points = entry_points if entry_points is not None else ENTRY_POINTS
    if not TYPEDOC_BIN.is_file():
        raise GenerationError(f"pinned typedoc binary missing: {TYPEDOC_BIN}. Run `npm install` in {TYPEDOC_DIR}.")
    if not TSCONFIG.is_file():
        raise GenerationError(f"studio-sdk tsconfig missing: {TSCONFIG}")

    with tempfile.TemporaryDirectory() as tmp:
        out_json = Path(tmp) / "studio-sdk.typedoc.json"
        cmd = [
            str(TYPEDOC_BIN),
            "--json",
            str(out_json),
            "--tsconfig",
            str(TSCONFIG),
            "--entryPointStrategy",
            "resolve",
            "--entryPoints",
            *entry_points,
            "--excludeExternals",
            "--excludePrivate",
            "--excludeInternal",
            "--readme",
            "none",
            "--logLevel",
            "Error",  # warnings (unresolved @links etc.) are non-fatal noise
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(STUDIO_SDK_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise GenerationError(f"typedoc exited {proc.returncode}:\n{(proc.stderr or proc.stdout).strip()}")
        if not out_json.is_file():
            raise GenerationError("typedoc produced no JSON output")
        try:
            project = json.loads(out_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise GenerationError(f"typedoc JSON is not valid JSON: {exc}") from exc

    if not isinstance(project, dict) or project.get("kind") != KIND_PROJECT:
        raise GenerationError("typedoc output is not a project reflection")
    return project


# --------------------------------------------------------------------------- #
# Project indexing
# --------------------------------------------------------------------------- #


def index_by_id(project: dict) -> dict[int, dict]:
    """Map every reflection id -> reflection, for resolving numeric references."""
    out: dict[int, dict] = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            if "id" in node and "kind" in node and node.get("variant") == "declaration":
                out[node["id"]] = node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(project)
    return out


def source_dir(refl: dict) -> str:
    """The first path segment under ``src/`` for a reflection's primary source
    (e.g. ``plugin`` for ``.../src/plugin/version.ts``). Returns "" when the
    source lives outside a package ``src/`` tree (a re-exported external type)."""
    sources = refl.get("sources") or []
    if not sources:
        return ""
    file_name = sources[0].get("fileName", "")
    marker = "/src/"
    if marker not in file_name:
        return ""
    return file_name.split(marker, 1)[1].split("/")[0]


def category_for(refl: dict, module_name: str) -> str:
    """The page slug a top-level export belongs to."""
    for cat in CATEGORIES:
        if module_name in cat["modules"]:
            return cat["slug"]
    directory = source_dir(refl)
    if directory:
        for cat in CATEGORIES:
            if directory in cat["dirs"]:
                return cat["slug"]
    return FALLBACK_SLUG


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


# --------------------------------------------------------------------------- #
# TypeDoc type -> string
# --------------------------------------------------------------------------- #


def type_str(t: dict | None) -> str:
    """Render a TypeDoc type object to a readable TypeScript type string."""
    if not isinstance(t, dict):
        return "unknown"
    kind = t.get("type")

    if kind == "intrinsic":
        return t.get("name", "unknown")
    if kind == "literal":
        value = t.get("value")
        if isinstance(value, str):
            return f'"{value}"'
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)
    if kind == "reference":
        name = t.get("name", "unknown")
        args = t.get("typeArguments") or []
        if args:
            return f"{name}<{', '.join(type_str(a) for a in args)}>"
        return name
    if kind == "array":
        inner = type_str(t.get("elementType"))
        return f"{_wrap(inner, t.get('elementType'))}[]"
    if kind == "union":
        return " | ".join(type_str(x) for x in t.get("types", []))
    if kind == "intersection":
        return " & ".join(type_str(x) for x in t.get("types", []))
    if kind == "tuple":
        return "[" + ", ".join(type_str(x) for x in t.get("elements", [])) + "]"
    if kind == "typeOperator":
        return f"{t.get('operator', '')} {type_str(t.get('target'))}".strip()
    if kind == "query":
        return f"typeof {type_str(t.get('queryType'))}"
    if kind == "indexedAccess":
        return f"{type_str(t.get('objectType'))}[{type_str(t.get('indexType'))}]"
    if kind == "reflection":
        decl = t.get("declaration") or {}
        alias = _collapsed_alias(decl)
        if alias is not None:
            return alias
        return _reflection_type_str(decl)
    if kind == "predicate":
        return f"{t.get('name', '')} is {type_str(t.get('targetType'))}"
    if kind == "templateLiteral":
        return "`" + _template_literal_str(t) + "`"
    if kind == "optional":
        return f"{type_str(t.get('elementType'))}?"
    if kind == "rest":
        return f"...{type_str(t.get('elementType'))}"
    if kind == "named-tuple-member":
        opt = "?" if t.get("isOptional") else ""
        return f"{t.get('name', '')}{opt}: {type_str(t.get('element'))}"
    if kind == "conditional":
        return (
            f"{type_str(t.get('checkType'))} extends {type_str(t.get('extendsType'))} "
            f"? {type_str(t.get('trueType'))} : {type_str(t.get('falseType'))}"
        )
    if kind == "unknown":
        return t.get("name", "unknown")
    return "unknown"


def _wrap(rendered: str, source: dict | None) -> str:
    """Parenthesise a compound type before an array/postfix operator."""
    if isinstance(source, dict) and source.get("type") in ("union", "intersection", "reflection"):
        return f"({rendered})"
    return rendered


def _template_literal_str(t: dict) -> str:
    head = t.get("head", "")
    tail = t.get("tail", []) or []
    parts = [head]
    for type_part, literal in tail:
        parts.append("${" + type_str(type_part) + "}")
        parts.append(literal)
    return "".join(parts)


def _reflection_type_str(decl: dict) -> str:
    """Render an inline reflection type: a function type, an index signature, or
    an object type literal. Kept compact — the full shape lives on the named
    interface/type-alias when there is one."""
    sigs = decl.get("signatures")
    if sigs:
        sig = sigs[0]
        params = ", ".join(_param_str(p) for p in sig.get("parameters", []) or [])
        return f"{_type_params_str(sig)}({params}) => {type_str(sig.get('type'))}"
    children = decl.get("children")
    if children:
        fields = []
        for child in children:
            opt = "?" if (child.get("flags") or {}).get("isOptional") else ""
            fields.append(f"{child.get('name')}{opt}: {type_str(child.get('type'))}")
        return "{ " + "; ".join(fields) + " }"
    index_sig = decl.get("indexSignatures")
    if index_sig:
        sig = index_sig[0]
        key = sig.get("parameters", [{}])[0]
        return f"{{ [{key.get('name', 'key')}: {type_str(key.get('type'))}]: {type_str(sig.get('type'))} }}"
    return "object"


def _param_str(param: dict) -> str:
    name = param.get("name", "")
    if name == "__namedParameters":
        name = "props"
    rest = "..." if (param.get("flags") or {}).get("isRest") else ""
    opt = "?" if (param.get("flags") or {}).get("isOptional") else ""
    annotated = type_str(param.get("type"))
    return f"{rest}{name}{opt}: {annotated}"


# --------------------------------------------------------------------------- #
# Cross-reference collection
# --------------------------------------------------------------------------- #


def collect_refs(t: dict | None, out: set[str]) -> None:
    """Collect the names of every ``reference`` type reachable from ``t`` (used
    to render a "Related types" line linking to locally documented symbols)."""
    if isinstance(t, dict):
        # A collapsed external alias (e.g. ApiClient) links by its recovered name;
        # stop here so its expanded internal structure is not walked.
        if t.get("type") == "reflection":
            alias = _collapsed_alias(t.get("declaration") or {})
            if alias is not None:
                out.add(alias)
                return
        # Only same-package references (not type parameters) resolve to a local page.
        if (
            t.get("type") == "reference"
            and isinstance(t.get("name"), str)
            and t.get("package") == "@tai42/studio-sdk"
            and not t.get("refersToTypeParameter")
        ):
            out.add(t["name"])
        for value in t.values():
            collect_refs(value, out)
    elif isinstance(t, list):
        for item in t:
            collect_refs(item, out)


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
    if iface and iface.get("kind") == KIND_INTERFACE:
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


def render_comment_text(comment: dict | None) -> str:
    """Plain summary text of a comment (no id_index needed for table cells)."""
    if not comment:
        return ""
    parts = []
    for part in comment.get("summary", []) or []:
        parts.append(part.get("text", ""))
    return "".join(parts).strip()


def render_members_table(iface: dict, heading: str) -> str:
    """Render an interface's / object's members as a table. Methods render their
    call signature in the Type column."""
    rows = []
    for member in sorted(iface.get("children", []) or [], key=lambda m: m.get("name", "")):
        name = member.get("name", "")
        if name.startswith("_"):
            continue
        optional = "?" if (member.get("flags") or {}).get("isOptional") else ""
        if member.get("kind") == KIND_METHOD:
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
# Per-symbol section rendering
# --------------------------------------------------------------------------- #


def render_symbol(
    refl: dict,
    id_index: dict[int, dict],
    location: dict[str, tuple[str, str]],
    current_slug: str,
) -> str:
    name = refl["name"]
    kind = refl.get("kind")
    parts: list[str] = [f"## {name}\n"]

    refs: set[str] = set()
    signature = ""
    table = ""

    if kind == KIND_FUNCTION:
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

    elif kind == KIND_INTERFACE:
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

    elif kind == KIND_TYPE_ALIAS:
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

    elif kind == KIND_VARIABLE:
        collect_refs(refl.get("type"), refs)
        const = "const " if (refl.get("flags") or {}).get("isConst") else "let "
        annotated = type_str(refl.get("type"))
        signature = f"{const}{name}: {annotated}"
        summary = render_comment(refl.get("comment"), id_index)
        parts.append(f"```ts\n{signature}\n```\n")
        if summary:
            parts.append(mdx_escape_prose(summary) + "\n")

    elif kind == KIND_ENUM:
        signature = f"enum {name}"
        summary = render_comment(refl.get("comment"), id_index)
        parts.append(f"```ts\n{signature}\n```\n")
        if summary:
            parts.append(mdx_escape_prose(summary) + "\n")
        rows = []
        for member in refl.get("children", []) or []:
            rows.append(
                f"| `{member.get('name')}` | {_table_code(type_str(member.get('type')))} | "
                f"{_table_text(render_comment_text(member.get('comment'))) or '—'} |"
            )
        if rows:
            table = "**Members**\n\n| Member | Value | Description |\n|---|---|---|\n" + "\n".join(rows) + "\n"
            parts.append(table)

    else:
        # Any other exported kind: at minimum a signature line so it is never dropped.
        signature = f"{name}"
        summary = render_comment(refl.get("comment"), id_index)
        parts.append(f"```ts\n{signature}\n```\n")
        if summary:
            parts.append(mdx_escape_prose(summary) + "\n")

    # Cross-links to related, locally documented types.
    related = sorted(n for n in refs if n != name and n in location)
    if related:
        links = ", ".join(f"[{n}](/{NAV_PREFIX}/{location[n][0]}#{location[n][1]})" for n in related)
        parts.append(f"**Related:** {links}\n")

    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------- #
# Page assembly
# --------------------------------------------------------------------------- #


def enumerate_exports(project: dict) -> list[tuple[dict, str]]:
    """Every top-level export across the three entry-point modules, as
    (reflection, module_name). A symbol re-exported from more than one module is
    documented once (first module wins, in module order)."""
    seen: set[str] = set()
    exports: list[tuple[dict, str]] = []
    modules = sorted(
        (m for m in project.get("children", []) if m.get("kind") == KIND_MODULE),
        key=lambda m: m.get("name", ""),
    )
    for module in modules:
        module_name = module.get("name", "")
        for child in module.get("children", []) or []:
            name = child.get("name", "")
            if not name or name in seen:
                continue
            # Guard the scope pin: skip anything flagged private/internal.
            flags = child.get("flags") or {}
            if flags.get("isPrivate") or flags.get("isExternal"):
                continue
            seen.add(name)
            exports.append((child, module_name))
    return exports


def build_reference(project: dict) -> tuple[dict[str, str], dict[str, list[str]], set[str]]:
    """Render every page into memory.

    Returns (slug -> mdx, slug -> rendered symbol names, all rendered names).
    Does not touch the filesystem. Raises GenerationError when no public export
    is found — the fail-loud guard against writing an empty reference."""
    global _SYMBOL_ID_MAP, _ALIAS_ORIGIN_TO_NAME
    _SYMBOL_ID_MAP = project.get("symbolIdMap") or {}
    id_index = index_by_id(project)
    exports = enumerate_exports(project)
    if not exports:
        raise GenerationError("no public exports found in the studio-sdk entry points")
    _ALIAS_ORIGIN_TO_NAME = _build_alias_origins(exports)

    # Pass 1 — assign every export to a page and compute its location, so cross
    # references can link across pages.
    assigned: dict[str, list[tuple[dict, str]]] = {cat["slug"]: [] for cat in CATEGORIES}
    location: dict[str, tuple[str, str]] = {}
    for refl, module_name in exports:
        slug = category_for(refl, module_name)
        assigned[slug].append((refl, module_name))
        location[refl["name"]] = (slug, anchor_for(refl["name"]))

    # Pass 2 — render each non-empty category page.
    pages: dict[str, str] = {}
    page_symbols: dict[str, list[str]] = {}
    all_symbols: set[str] = set()

    for cat in CATEGORIES:
        slug = cat["slug"]
        members = sorted(assigned[slug], key=lambda rm: rm[0].get("name", ""))
        if not members:
            continue
        body = [frontmatter(cat["title"], cat["description"], cat["icon"]), ""]
        body.append(mdx_escape_prose(cat["description"]) + "\n")
        names: list[str] = []
        for refl, _module in members:
            body.append(render_symbol(refl, id_index, location, slug))
            names.append(refl["name"])
            all_symbols.add(refl["name"])
        pages[slug] = "\n".join(body)
        page_symbols[slug] = names

    if not pages:
        raise GenerationError("no pages rendered from the studio-sdk exports")

    pages["index"] = render_index_page(page_symbols)
    return pages, page_symbols, all_symbols


def render_index_page(page_symbols: dict[str, list[str]]) -> str:
    """The Studio SDK reference landing page: a CardGroup over the categories."""
    body = [
        frontmatter(
            "Studio SDK",
            "The generated @tai42/studio-sdk reference — the plugin contract, hooks, and design system.",
            "puzzle-piece",
        ),
        "",
        "The Studio SDK reference is generated from the doc comments of the public "
        "`@tai42/studio-sdk` exports — the plugin contract every Studio plugin implements, "
        "the hooks and providers each feature builds on, and the design-system components.\n",
        "<CardGroup cols={2}>",
    ]
    for cat in CATEGORIES:
        slug = cat["slug"]
        if slug not in page_symbols:
            continue
        count = len(page_symbols[slug])
        noun = "export" if count == 1 else "exports"
        body.append(
            f'  <Card title="{cat["title"]}" icon="{cat["icon"]}" '
            f'href="/{NAV_PREFIX}/{slug}">\n'
            f"    {mdx_escape_prose(cat['description'])} ({count} {noun})\n"
            f"  </Card>"
        )
    body.append("</CardGroup>")
    return "\n".join(body) + "\n"


# --------------------------------------------------------------------------- #
# docs.json nav wiring
# --------------------------------------------------------------------------- #


def build_nav(slugs: list[str]) -> dict:
    """Parse docs.json and return the FULL mutated docs.json data with the
    Reference > "Studio SDK" group added / refreshed (its pages matching the
    generated files, inserted directly AFTER the Catalog group). The rest of
    docs.json is preserved byte-for-byte otherwise.

    Raises GenerationError when docs.json has no Reference tab. This is a PURE
    build step run BEFORE any page is written, so a malformed docs.json fails the
    run without leaving partial output on disk; ``write_nav`` performs the write."""
    data = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    pages = [f"{NAV_PREFIX}/index"] + [f"{NAV_PREFIX}/{s}" for s in slugs]
    group = {"group": "Studio SDK", "icon": "puzzle-piece", "pages": pages}

    for tab in data["navigation"]["tabs"]:
        if tab.get("tab") != "Reference":
            continue
        groups = tab["groups"]
        # Replace an existing Studio SDK group in place, else insert after Catalog.
        for i, existing in enumerate(groups):
            if existing.get("group") == "Studio SDK":
                groups[i] = group
                break
        else:
            insert_at = len(groups)
            for i, existing in enumerate(groups):
                if existing.get("group") == "Catalog":
                    insert_at = i + 1
                    break
            groups.insert(insert_at, group)
        return data
    raise GenerationError("docs.json: Reference tab not found")


def write_nav(data: dict) -> None:
    """Write the mutated docs.json data produced by ``build_nav``."""
    DOCS_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def _ordered_slugs(page_symbols: dict[str, list[str]]) -> list[str]:
    """Category slugs that were actually rendered, in CATEGORIES order."""
    return [cat["slug"] for cat in CATEGORIES if cat["slug"] in page_symbols]


def main() -> int:
    # 1. Run TypeDoc.
    try:
        project = run_typedoc()
    except GenerationError as exc:
        print(f"gen_studio_sdk: typedoc failed: {exc}", file=sys.stderr)
        return 1

    # 2. Render everything into memory (no filesystem writes yet).
    try:
        pages, page_symbols, all_symbols = build_reference(project)
    except GenerationError as exc:
        print(f"gen_studio_sdk: rendering failed: {exc}", file=sys.stderr)
        return 1

    # 3. Checklist — every required symbol must be present as a rendered heading
    #    with a signature. Fail before writing. (The stricter params/props-table
    #    guarantee is asserted by the test suite, not enforced here.)
    missing = [s for s in REQUIRED_SYMBOLS if s not in all_symbols]
    if missing:
        print(
            "gen_studio_sdk: required symbols missing from generated reference: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    all_text = "\n".join(pages.values())
    for sym in REQUIRED_SYMBOLS:
        if f"## {sym}\n" not in all_text:
            print(f"gen_studio_sdk: required symbol {sym!r} not rendered as a heading", file=sys.stderr)
            return 1

    # 3b. Build (and validate) the docs.json nav mutation BEFORE any write, so a
    #     malformed docs.json fails the run without leaving pages unwired on disk.
    slugs = _ordered_slugs(page_symbols)
    try:
        nav_data = build_nav(slugs)
    except GenerationError as exc:
        print(f"gen_studio_sdk: docs.json nav update failed: {exc}", file=sys.stderr)
        return 1

    # 4. All checks passed — safe to write. Clean prior generated pages so a
    #    removed category never leaves an orphan page.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for existing in OUT_DIR.glob("*.mdx"):
        existing.unlink()

    (OUT_DIR / "index.mdx").write_text(pages["index"], encoding="utf-8")
    for slug in slugs:
        (OUT_DIR / f"{slug}.mdx").write_text(pages[slug], encoding="utf-8")

    write_nav(nav_data)

    total = len(all_symbols)
    print(
        f"gen_studio_sdk: wrote {len(slugs) + 1} pages to {OUT_DIR} "
        f"({total} public exports; all {len(REQUIRED_SYMBOLS)} required present)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
