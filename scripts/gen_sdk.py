#!/usr/bin/env python3
"""Generate the Python SDK reference from source docstrings via griffe.

This script loads the PUBLIC API of ``tai42_contract``, ``tai42_kit``, and the
``tai42_skeleton`` app surface as a griffe object model (static analysis of the
source tree — no imports are executed) and renders one MDX reference page per
logical area under ``reference/python-sdk/``. Docstrings are the source of
truth; every rendered symbol traces to a real object in the source.

Run it from a context where the three source packages resolve — the
tai42-skeleton virtualenv does::

    cd tai42/core/skeleton && uv run python ../../../tai-docs/scripts/gen_sdk.py

Fail-loud contract: the script renders every page into memory and validates the
required-symbol checklist BEFORE touching the output directory. If a source
package cannot be loaded, or a required Protocol/ABC is missing from the
rendered output, it exits non-zero and writes NOTHING — it never overwrites a
good reference with an empty or partial one.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    from griffe import Alias, Class, Docstring, Function, GriffeLoader, Object
except ImportError as exc:  # pragma: no cover - environment guard
    print(f"gen_sdk: griffe is not importable: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
WORKSPACE_ROOT = DOCS_ROOT.parent

SRC_PATHS = [
    WORKSPACE_ROOT / "tai42" / "core" / "contract" / "src",
    WORKSPACE_ROOT / "tai42" / "core" / "kit" / "src",
    WORKSPACE_ROOT / "tai42" / "core" / "skeleton" / "src",
]

OUT_DIR = DOCS_ROOT / "reference" / "python-sdk"
DOCS_JSON = DOCS_ROOT / "docs.json"


# --------------------------------------------------------------------------- #
# Page specification: each page renders one or more modules. Order is stable so
# the generated nav and anchors do not churn between runs.
# --------------------------------------------------------------------------- #

PAGES: list[dict] = [
    {
        "slug": "contract-app",
        "title": "App facade (tai42_contract.app)",
        "description": "The assembled TaiApp facade and its per-feature namespaces.",
        "icon": "layer-group",
        "modules": ["tai42_contract.app", "tai42_contract.app.facets"],
    },
    {
        "slug": "contract-agent",
        "title": "Agents (tai42_contract.agent)",
        "description": "The Agent base class plugin authors subclass.",
        "icon": "robot",
        "modules": ["tai42_contract.agent"],
    },
    {
        "slug": "contract-versioning",
        "title": "Versioning (tai42_contract.versioning)",
        "description": "The VersionedStore primitive behind presets and policies.",
        "icon": "code-branch",
        "modules": ["tai42_contract.versioning"],
    },
    {
        "slug": "contract-presets",
        "title": "Presets (tai42_contract.presets)",
        "description": "The PresetStore protocol and preset document models.",
        "icon": "sliders",
        "modules": ["tai42_contract.presets"],
    },
    {
        "slug": "contract-connectors",
        "title": "Connectors (tai42_contract.connectors)",
        "description": "The ProviderDescriptor a connector plugin declares.",
        "icon": "plug",
        "modules": ["tai42_contract.connectors.providers"],
    },
    {
        "slug": "contract-extensions",
        "title": "Extensions (tai42_contract.extensions)",
        "description": "The ExtensionKind taxonomy and extension base surface.",
        "icon": "puzzle-piece",
        "modules": ["tai42_contract.extensions"],
    },
    {
        "slug": "contract-monitoring",
        "title": "Monitoring (tai42_contract.monitoring)",
        "description": "The MonitoringReader and MonitoringWriter protocols.",
        "icon": "chart-line",
        "modules": ["tai42_contract.monitoring.reader", "tai42_contract.monitoring.writer"],
    },
    {
        "slug": "contract-storage",
        "title": "Storage (tai42_contract.storage)",
        "description": "The Storage protocol a storage provider implements.",
        "icon": "database",
        "modules": ["tai42_contract.storage"],
    },
    {
        "slug": "contract-backend",
        "title": "Backends (tai42_contract.backend)",
        "description": "The Backend protocol a compute backend implements.",
        "icon": "server",
        "modules": ["tai42_contract.backend"],
    },
    {
        "slug": "contract-channels",
        "title": "Channels (tai42_contract.channels)",
        "description": "The Channel protocol a delivery channel plugin implements.",
        "icon": "paper-plane",
        "modules": ["tai42_contract.channels"],
    },
    {
        "slug": "contract-accounts",
        "title": "Accounts (tai42_contract.accounts)",
        "description": "The AccountsProvider contract, its registry, and the login-method metadata models.",
        "icon": "user-lock",
        "modules": [
            "tai42_contract.accounts.provider",
            "tai42_contract.accounts.models",
            "tai42_contract.accounts.registry",
        ],
    },
    {
        "slug": "contract-tools",
        "title": "Tools (tai42_contract.tools)",
        "description": "Tool registration types and the app tools namespace.",
        "icon": "wrench",
        "modules": ["tai42_contract.tools"],
    },
    {
        "slug": "contract-manifest",
        "title": "Manifest (tai42_contract.manifest)",
        "description": "The manifest model a server loads at startup.",
        "icon": "file-lines",
        "modules": ["tai42_contract.manifest"],
    },
    {
        "slug": "contract-plugins",
        "title": "Plugins (tai42_contract.plugins)",
        "description": "The PluginSpec model behind tai-plugin.yml.",
        "icon": "store",
        "modules": ["tai42_contract.plugins"],
    },
    {
        "slug": "kit-clients",
        "title": "Pooled clients (tai42_kit.clients)",
        "description": "Pooled Postgres/Redis clients and connection settings.",
        "icon": "network-wired",
        "modules": ["tai42_kit.clients"],
    },
    {
        "slug": "kit-llm",
        "title": "LLM factories (tai42_kit.llm)",
        "description": "LLM, embedding, checkpoint, and store factories.",
        "icon": "brain",
        "modules": ["tai42_kit.llm"],
    },
    {
        "slug": "kit-settings",
        "title": "Settings (tai42_kit.settings)",
        "description": "The base settings class and the settings registry.",
        "icon": "gear",
        "modules": ["tai42_kit.settings"],
    },
    {
        "slug": "kit-transport",
        "title": "Transports (tai42_kit.transport)",
        "description": "UDS transports and the MCP transport factory.",
        "icon": "route",
        "modules": ["tai42_kit.transport"],
    },
    {
        "slug": "kit-net",
        "title": "Network guard (tai42_kit.net)",
        "description": "The URL guard and safe fetch helpers.",
        "icon": "shield-halved",
        "modules": ["tai42_kit.net"],
    },
    {
        "slug": "kit-logging",
        "title": "Logging (tai42_kit.logging)",
        "description": "Structured logging settings and setup.",
        "icon": "file-lines",
        "modules": ["tai42_kit.logging"],
    },
    {
        "slug": "skeleton-app",
        "title": "Skeleton app (tai42_skeleton.app)",
        "description": "The concrete TaiMCP app, including the raw fastmcp escape hatch.",
        "icon": "microchip",
        "modules": ["tai42_skeleton.app.server"],
    },
    {
        "slug": "skeleton-asgi",
        "title": "ASGI factory (tai42_skeleton.asgi)",
        "description": "The public create_app factory for embedding the server in a user-owned ASGI process.",
        "icon": "server",
        "modules": ["tai42_skeleton.asgi"],
    },
]

# The public Protocols/ABCs a plugin author implements, the escape-hatch
# accessor, and the guarded fetch helper. Every one MUST appear as a rendered
# heading or the run fails.
REQUIRED_SYMBOLS = [
    "Agent",
    "VersionedStore",
    "AppVersioning",
    "AppPresets",
    "PresetStore",
    "MonitoringReader",
    "MonitoringWriter",
    "ProviderDescriptor",
    "ExtensionKind",
    "TaiApp",
    "Backend",
    "Storage",
    "Channel",
    "PluginSpec",
    "fastmcp",
    "fetch_url",
]


# --------------------------------------------------------------------------- #
# MDX text helpers
# --------------------------------------------------------------------------- #

# RST cross-reference roles (``:class:`Foo```) that appear in docstrings; strip
# the role prefix so the backtick span renders as plain inline code.
_RST_ROLE = re.compile(r":(?:class|mod|func|meth|obj|attr|data|exc|ref|term):(`)")
# Sphinx ``~pkg.mod.Name`` shorthand inside a code span -> just ``Name``.
_RST_TILDE = re.compile(r"`~([A-Za-z0-9_.]+)`")
_CODE_SPAN = re.compile(r"``[^`]*``|`[^`]*`")
# Fenced code block (```lang ... ```). Its body must pass through verbatim:
# escaping it would corrupt code such as ``dict[str, Any]`` displays or
# comparison operators inside a docstring example.
_CODE_FENCE = re.compile(r"^```.*?^```[ \t]*$", re.DOTALL | re.MULTILINE)


def _tilde_last(match: re.Match) -> str:
    return "`" + match.group(1).rsplit(".", 1)[-1] + "`"


def mdx_escape_prose(text: str) -> str:
    """Escape MDX-hostile characters in prose while leaving code untouched:
    fenced blocks (```...```) and inline-code spans (single- or
    double-backtick) pass through verbatim, so fenced examples and annotations
    like ``dict[str, Any]`` survive while stray ``{`` / ``<`` in narrative
    cannot break the MDX parser."""
    out: list[str] = []
    last = 0
    for fence in _CODE_FENCE.finditer(text):
        out.append(_escape_prose_segment(text[last : fence.start()]))
        out.append(fence.group(0))  # fenced block: leave verbatim
        last = fence.end()
    out.append(_escape_prose_segment(text[last:]))
    return "".join(out)


def _escape_prose_segment(text: str) -> str:
    """Escape one fence-free stretch, leaving inline-code spans verbatim."""
    text = _RST_ROLE.sub(r"\1", text)
    text = _RST_TILDE.sub(_tilde_last, text)

    out: list[str] = []
    last = 0
    for match in _CODE_SPAN.finditer(text):
        out.append(_escape_segment(text[last : match.start()]))
        out.append(match.group(0))  # code span: leave verbatim
        last = match.end()
    out.append(_escape_segment(text[last:]))
    return "".join(out)


def _escape_segment(seg: str) -> str:
    return seg.replace("{", "&#123;").replace("}", "&#125;").replace("<", "&lt;").replace(">", "&gt;")


def frontmatter(title: str, description: str, icon: str) -> str:
    # Quote to keep YAML happy regardless of punctuation in the values.
    return f'---\ntitle: "{title}"\ndescription: "{description}"\nicon: "{icon}"\n---\n'


# --------------------------------------------------------------------------- #
# griffe object -> MDX rendering
# --------------------------------------------------------------------------- #


def resolve(member: Object | Alias) -> Object | None:
    """Resolve an alias to its concrete target; return None if unresolvable."""
    if member.is_alias:
        try:
            return member.final_target  # type: ignore[attr-defined]
        except Exception:
            return None
    return member  # type: ignore[return-value]


def public_targets(module: Object) -> list[Object]:
    """The public, source-defined objects a module exposes, in stable order.

    Honours ``__all__`` when present (resolving re-exports to their target);
    otherwise takes the module's own public classes/functions/attributes.

    A same-named submodule shadows a re-exported object in griffe's model
    (``from pkg.helper import helper`` makes ``pkg.helper`` resolve to the
    submodule, not the function), so an ``__all__`` export that resolves to a
    module is dereferenced to the submodule's same-named member — repeatedly,
    when that member is itself a shadowing submodule. An export whose chain
    reaches no renderable member (missing name, or a cycle back to a visited
    module) cannot be rendered — that raises rather than silently dropping a
    declared export.
    """
    targets: list[Object] = []
    seen: set[str] = set()

    exports = module.exports  # list[str] from __all__, or None/False
    if exports:
        names = [n for n in exports if isinstance(n, str) and not n.startswith("_")]
        candidates = [(n, module.members.get(n)) for n in names]
        from_all = True
    else:
        candidates = [(n, m) for n, m in module.members.items() if not n.startswith("_") and not m.is_alias]
        from_all = False

    for name, member in candidates:
        if member is None:
            continue
        target = resolve(member)
        if target is None:
            continue
        if from_all:
            visited: set[str] = set()
            while target.kind.value == "module":
                if target.path in visited:
                    raise RuntimeError(
                        f"{module.path}: __all__ export {name!r} cycles through "
                        f"module {target.path} without reaching a renderable member"
                    )
                visited.add(target.path)
                inner = target.members.get(name)
                inner = resolve(inner) if inner is not None else None
                if inner is None:
                    raise RuntimeError(
                        f"{module.path}: __all__ export {name!r} resolves to module "
                        f"{target.path}, which has no same-named member to render"
                    )
                target = inner
        if target.kind.value not in ("class", "function", "attribute"):
            continue
        if target.path in seen:
            continue
        seen.add(target.path)
        targets.append(target)
    return targets


def _param_pieces(func: Function) -> list[str]:
    pieces: list[str] = []
    # Track the boundary markers so a keyword-only parameter renders after a bare
    # `*` separator and a positional-only group is closed with `/`, mirroring the
    # real source signature (griffe records each parameter's kind).
    star_emitted = False  # a bare `*` or a `*args` separator is already present
    last_positional_only = -1  # index in `pieces` of the last positional-only param
    for p in func.parameters:
        kind = getattr(p.kind, "value", "")
        # A keyword-only parameter needs a preceding `*`; skip it if a variadic
        # positional (`*args`) already introduced the keyword-only section.
        if kind == "keyword-only" and not star_emitted:
            pieces.append("*")
            star_emitted = True
        name = p.name
        if kind == "variadic positional":
            name = "*" + name
            star_emitted = True
        elif kind == "variadic keyword":
            name = "**" + name
        piece = name
        if p.annotation is not None:
            piece += f": {p.annotation}"
        # A variadic parameter (`*args`/`**kwargs`) never carries a default in a
        # real signature, so a default recorded for one is spurious and is dropped.
        if p.default is not None and kind not in ("variadic positional", "variadic keyword"):
            piece += f" = {p.default}"
        pieces.append(piece)
        if kind == "positional-only":
            last_positional_only = len(pieces) - 1
    if last_positional_only >= 0:
        pieces.insert(last_positional_only + 1, "/")
    return pieces


def render_signature(obj: Object) -> str:
    if isinstance(obj, Function) or obj.kind.value == "function":
        params = _param_pieces(obj)  # type: ignore[arg-type]
        ret = f" -> {obj.returns}" if getattr(obj, "returns", None) is not None else ""
        # griffe tags coroutine functions with an ``async`` label; surface it so
        # a coroutine renders as ``async name(...)`` and never masquerades as a
        # plain synchronous callable (mirrors the ``property`` label read below).
        labels = getattr(obj, "labels", set()) or set()
        prefix = "async " if "async" in labels else ""
        multiline = len(", ".join(params)) > 76 and len(params) > 1
        if multiline:
            body = ",\n    ".join(params)
            return f"{prefix}{obj.name}(\n    {body},\n){ret}"
        return f"{prefix}{obj.name}({', '.join(params)}){ret}"

    if isinstance(obj, Class) or obj.kind.value == "class":
        bases = [str(b) for b in getattr(obj, "bases", [])]
        bases = [b for b in bases if b and b != "object"]
        base_str = f"({', '.join(bases)})" if bases else ""
        return f"class {obj.name}{base_str}"

    # attribute / property
    line = obj.name
    if getattr(obj, "annotation", None) is not None:
        line += f": {obj.annotation}"
    if getattr(obj, "value", None) is not None:
        line += f" = {obj.value}"
    return line


def _doc_sections(obj: Object):
    """Return (prose, param_docs, returns_doc) parsed from the docstring."""
    prose_parts: list[str] = []
    param_docs: dict[str, str] = {}
    returns_doc = ""
    if not obj.docstring:
        return "", param_docs, returns_doc
    try:
        doc = Docstring(obj.docstring.value, parser="google", parent=obj)
        sections = doc.parse()
    except Exception:
        return obj.docstring.value.strip(), param_docs, returns_doc

    for section in sections:
        kind = section.kind.value
        if kind == "text":
            prose_parts.append(str(section.value))
        elif kind == "parameters":
            for item in section.value:
                param_docs[item.name] = (item.description or "").strip()
        elif kind == "returns":
            # griffe's google parser splits a same-indent multi-line Returns block
            # into one item per line; join every item's description so a multi-line
            # return description renders as one complete text, not a truncated first
            # line.
            descriptions = [item.description.strip() for item in section.value if item.description]
            returns_doc = " ".join(descriptions)
    return "\n\n".join(prose_parts).strip(), param_docs, returns_doc


def _first_line(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    # First sentence / first line, whichever is shorter, as a one-line summary.
    line = text.splitlines()[0].strip()
    return mdx_escape_prose(line)


def _table_code(value) -> str:
    """A backtick code cell safe inside a Markdown table: literal pipes in the
    value (e.g. ``list[str] | None``) are escaped so they don't split columns."""
    return "`" + str(value).replace("|", "\\|") + "`"


def _table_text(text: str) -> str:
    """Prose safe inside a Markdown table cell."""
    return mdx_escape_prose(text.replace("\n", " ")).replace("|", "\\|")


def render_params_table(func: Function, param_docs: dict[str, str]) -> str:
    rows = []
    for p in func.parameters:
        if p.name in ("self", "cls"):
            continue
        typ = _table_code(p.annotation) if p.annotation is not None else "—"
        default = _table_code(p.default) if p.default is not None else "—"
        desc = _table_text(param_docs.get(p.name, "")) or "—"
        rows.append(f"| `{p.name}` | {typ} | {default} | {desc} |")
    if not rows:
        return ""
    header = "| Parameter | Type | Default | Description |\n|---|---|---|---|\n"
    return "**Parameters**\n\n" + header + "\n".join(rows) + "\n"


def _has_docstring(member: Object) -> bool:
    return bool(member.docstring and member.docstring.value.strip())


def render_attrs_table(cls: Object) -> str:
    """A compact table of the class's plain data members (fields and simple
    properties). Members that carry their own docstring are rendered as full
    subsections instead (see ``render_object``), so they are not duplicated
    here."""
    rows = []
    for name, member in cls.members.items():
        if name.startswith("_") or member.is_alias:
            continue
        if member.kind.value != "attribute":
            continue
        if _has_docstring(member):
            continue
        labels = getattr(member, "labels", set()) or set()
        typ = _table_code(member.annotation) if getattr(member, "annotation", None) is not None else "—"
        note = " *(property)*" if "property" in labels else ""
        rows.append(f"| `{name}`{note} | {typ} |")
    if not rows:
        return ""
    header = "| Attribute | Type |\n|---|---|\n"
    return "**Attributes**\n\n" + header + "\n".join(rows) + "\n"


def render_object(obj: Object, level: int = 2) -> str:
    """Render one top-level object (class / function / attribute) to MDX."""
    hashes = "#" * level
    parts: list[str] = [f"{hashes} {obj.name}\n"]
    parts.append(f"`{obj.path}`\n")

    parts.append("```python\n" + render_signature(obj) + "\n```\n")

    prose, param_docs, returns_doc = _doc_sections(obj)
    if prose:
        parts.append(mdx_escape_prose(prose) + "\n")

    if isinstance(obj, Class) or obj.kind.value == "class":
        attrs = render_attrs_table(obj)
        if attrs:
            parts.append(attrs)
        # Methods, plus documented properties (e.g. the fastmcp escape hatch),
        # each get their own subsection with signature + docstring.
        detailed = [
            m
            for n, m in obj.members.items()
            if not n.startswith("_")
            and not m.is_alias
            and (m.kind.value == "function" or (m.kind.value == "attribute" and _has_docstring(m)))
        ]
        if detailed:
            parts.append(f"{'#' * (level + 1)} Members\n")
            for member in detailed:
                parts.append(render_object(member, level + 2))
    elif isinstance(obj, Function) or obj.kind.value == "function":
        table = render_params_table(obj, param_docs)  # type: ignore[arg-type]
        if table:
            parts.append(table)
        if returns_doc:
            parts.append(f"**Returns** — {mdx_escape_prose(returns_doc)}\n")

    return "\n".join(parts) + "\n"


def render_page(loader: GriffeLoader, spec: dict) -> tuple[str, list[str]]:
    """Render one page; return (mdx_text, list_of_rendered_symbol_names)."""
    body: list[str] = [frontmatter(spec["title"], spec["description"], spec["icon"]), ""]
    rendered: list[str] = []

    lead_done = False
    for module_path in spec["modules"]:
        module = loader.modules_collection[module_path]
        if not lead_done and module.docstring:
            lead = _doc_sections(module)[0]
            if lead:
                body.append(mdx_escape_prose(lead) + "\n")
            lead_done = True
        for obj in public_targets(module):
            body.append(render_object(obj, level=2))
            rendered.append(obj.name)
            # class methods count toward coverage too (e.g. fastmcp property)
            if obj.kind.value == "class":
                for n, m in obj.members.items():
                    if not n.startswith("_") and not m.is_alias:
                        rendered.append(n)

    if len(rendered) == 0:
        raise RuntimeError(f"page {spec['slug']}: rendered no symbols")
    return "\n".join(body), rendered


# --------------------------------------------------------------------------- #
# docs.json nav wiring
# --------------------------------------------------------------------------- #


def update_nav(slugs: list[str]) -> None:
    """Rewrite ONLY the Reference > Python SDK group's pages to match the
    generated files, preserving the rest of docs.json byte-for-byte otherwise."""
    data = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    pages = ["reference/python-sdk/index"] + [f"reference/python-sdk/{s}" for s in slugs]
    for tab in data["navigation"]["tabs"]:
        if tab.get("tab") != "Reference":
            continue
        for group in tab["groups"]:
            if group.get("group") == "Python SDK":
                group["pages"] = pages
                # ensure_ascii=False so hand-authored non-ASCII in docs.json
                # (e.g. em-dashes) survives a partial regen byte-for-byte and
                # never re-encodes to \\uXXXX escapes -- matches gen_cli.
                DOCS_JSON.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                return
    raise RuntimeError("docs.json: Reference > Python SDK group not found")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def load_model() -> GriffeLoader:
    """Load the three source packages into one griffe model with aliases
    resolved. Raises if a source path is missing or a package fails to load."""
    for path in SRC_PATHS:
        if not path.is_dir():
            raise FileNotFoundError(f"source path missing: {path}")
    loader = GriffeLoader(search_paths=[str(p) for p in SRC_PATHS])
    for pkg in ("tai42_contract", "tai42_kit", "tai42_skeleton"):
        loader.load(pkg)
    loader.resolve_aliases(external=True, implicit=True)
    return loader


def build_pages(loader: GriffeLoader) -> tuple[dict[str, str], set[str]]:
    """Render every page into memory. Returns (slug -> mdx, all symbol names).
    Does not touch the filesystem."""
    rendered_pages: dict[str, str] = {}
    all_symbols: set[str] = set()
    for spec in PAGES:
        text, symbols = render_page(loader, spec)
        rendered_pages[spec["slug"]] = text
        all_symbols.update(symbols)
    return rendered_pages, all_symbols


def main() -> int:
    try:
        loader = load_model()
    except Exception as exc:
        print(f"gen_sdk: failed to load source packages: {exc}", file=sys.stderr)
        return 1

    # Render everything into memory first; only write once the checklist passes.
    try:
        rendered_pages, all_symbols = build_pages(loader)
    except Exception as exc:
        print(f"gen_sdk: rendering failed: {exc}", file=sys.stderr)
        return 1

    missing = [s for s in REQUIRED_SYMBOLS if s not in all_symbols]
    if missing:
        print(
            "gen_sdk: required symbols missing from generated reference: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    # All checks passed — safe to write. Clean prior generated pages (keep the
    # hand-written index) so a removed module never leaves an orphan page.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for existing in OUT_DIR.glob("*.mdx"):
        if existing.name != "index.mdx":
            existing.unlink()

    for slug, text in rendered_pages.items():
        (OUT_DIR / f"{slug}.mdx").write_text(text, encoding="utf-8")

    update_nav([spec["slug"] for spec in PAGES])

    print(
        f"gen_sdk: wrote {len(rendered_pages)} pages to {OUT_DIR} "
        f"({len(all_symbols)} public symbols; all required present)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
