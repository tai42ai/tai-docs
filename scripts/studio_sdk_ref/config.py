"""Static configuration for the Studio SDK reference generator.

Paths, the TypeDoc ReflectionKind enum, the page/category specification, and the
required-symbol coverage checklist. Every mutable value here (the entry points,
the output directory, the TypeDoc binary and its inputs) is read by the other
phase modules through this module object at call time, so a test that reassigns
``config.OUT_DIR``/``config.ENTRY_POINTS``/``config.TYPEDOC_BIN`` is observed by
``run_typedoc`` and ``main``.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

SCRIPT_DIR = Path(__file__).resolve().parent.parent
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
