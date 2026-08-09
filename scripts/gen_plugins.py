#!/usr/bin/env python3
"""Generate the Plugins section from the marketplace public API.

The only input is the marketplace registry over HTTP (base URL from
``MARKETPLACE_URL``, production default below). Listing ENUMERATION comes from
the UNCAPPED ``GET /api/v1/items`` route — the public ``/api/v1/search`` route
page-caps at 100 and would silently truncate the section. Per listing the
generator fetches the detail spec, the docs tree, and each referenced image, then
writes one page per plugin under ``plugins/{namespace}/{name}.mdx`` (the slug the
marketplace's ``docs_url`` pins).

Each page is a GENERATED header (title, kind badge, install line, permissions
table, and a provides list with per-item anchors, all from the served spec)
followed by the plugin's own ``docs/index.mdx`` body (front matter stripped; its
title/description feed the page front matter). Extra docs pages land at
``plugins/{namespace}/{name}/{page}.mdx``. Images are downloaded into
``plugins/images/{namespace}-{name}/`` and references are rewritten, so the
committed tree is self-contained (Mintlify serves committed files only).

Defense in depth at the one place third-party content becomes a committed page:
every fetched docs payload is re-run through the kit's canonical
``validate_docs`` (``first_party = namespace == "tai42"``) and every downloaded
image is re-sniffed raster-only by magic bytes — a committed SVG would ship live,
so it is refused. Network failure or an empty listing set is a loud nonzero exit
(never an empty-section commit).

The generator also emits ``plugins/_registry.json`` — the listings + item-row
snapshot the offline consumers (gen_toolbox_table, gen_capability_map,
check_docs_refs) read instead of the network — and owns a top-level ``Plugins``
nav group in ``docs.json``, grouped by each plugin's FIRST provides item kind
through the fixed label table below.

Run against a live marketplace::

    MARKETPLACE_URL=https://marketplace.tai42.ai python3 scripts/gen_plugins.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
PLUGINS_DIR = DOCS_ROOT / "plugins"
IMAGES_DIR = PLUGINS_DIR / "images"
REGISTRY_OUT = PLUGINS_DIR / "_registry.json"
DOCS_JSON = DOCS_ROOT / "docs.json"

sys.path.insert(0, str(SCRIPT_DIR))
from kit_docs import DocsValidationError, validate_docs_payload  # noqa: E402

DEFAULT_MARKETPLACE_URL = "https://marketplace.tai42.ai"

# First provides-item kind -> nav group label. FIXED: an unmapped kind is a loud
# failure naming it (a new listing's kind gets its row added when it is ruled in).
# connector and mcp-server SHARE one shelf (R10).
_SHELF_GROUP = "Connect outside systems"
KIND_GROUP_LABELS: dict[str, str] = {
    "tool": "Tools",
    "identity": "Identity",
    "agent": "Agents",
    "backend": "Backends",
    "channel": "Channels",
    "config": "Config",
    "monitoring": "Monitoring",
    "storage": "Storage",
    "webhook-verifier": "Webhook verifiers",
    "connector": _SHELF_GROUP,
    "mcp-server": _SHELF_GROUP,
}
# Deterministic nav order of the groups above.
GROUP_ORDER: tuple[str, ...] = (
    "Tools",
    "Identity",
    "Agents",
    "Backends",
    "Channels",
    "Config",
    "Monitoring",
    "Storage",
    "Webhook verifiers",
    _SHELF_GROUP,
)
GROUP_ICONS: dict[str, str] = {
    "Tools": "wrench",
    "Identity": "id-card",
    "Agents": "robot",
    "Backends": "server",
    "Channels": "paper-plane",
    "Config": "gear",
    "Monitoring": "chart-line",
    "Storage": "database",
    "Webhook verifiers": "bolt",
    _SHELF_GROUP: "plug",
}

# Per-kind item badge label used inside a page's provides list.
_ITEM_KIND_LABELS: dict[str, str] = {
    "tool": "Tool",
    "extension": "Extension",
    "agent": "Agent",
    "connector": "Connector",
    "mcp-server": "MCP server",
    "channel": "Channel",
    "backend": "Backend",
    "storage": "Storage",
    "monitoring": "Monitoring",
    "webhook-verifier": "Webhook verifier",
    "config": "Config",
    "identity": "Identity",
    "router": "Router",
    "middleware": "Middleware",
    "studio-plugin": "Studio plugin",
}

_FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
# A relative markdown/JSX image reference into the docs image tree.
_IMG_REF_RE = re.compile(r"(!\[[^\]]*\]\(\s*)(\.?/?(?:docs/)?images/[^)\s]+)")


class GenError(RuntimeError):
    """A loud generation failure — the run exits nonzero writing nothing."""


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #


def _base_url() -> str:
    return os.environ.get("MARKETPLACE_URL", DEFAULT_MARKETPLACE_URL).rstrip("/")


def _get(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise GenError(f"marketplace request failed for {url}: {exc}") from exc


def _get_json(url: str) -> dict:
    raw = _get(url)
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GenError(f"marketplace returned invalid JSON for {url}: {exc}") from exc
    if not isinstance(doc, dict) or "data" not in doc:
        raise GenError(f"marketplace response for {url} is not a data envelope")
    return doc["data"]


def fetch_listing_refs(base: str) -> list[tuple[str, str]]:
    """Every listed plugin ref (namespace, name), deduped, from the uncapped items route."""
    data = _get_json(f"{base}/api/v1/items")
    items = data.get("items")
    if not isinstance(items, list):
        raise GenError("items route returned no items array")
    refs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in items:
        ref = (row["namespace"], row["listing"])
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    if not refs:
        raise GenError("marketplace enumerated ZERO listings — refusing to commit an empty Plugins section")
    return sorted(refs)


def fetch_listing(base: str, namespace: str, name: str) -> tuple[dict, dict[str, bytes]]:
    """Return ``(spec, docs_files)`` for one listing.

    ``spec`` is the latest published version's validated PluginSpec dict.
    ``docs_files`` maps every ``docs/…`` path to its bytes (mdx inline, images
    downloaded from the asset route), the shape ``validate_docs`` consumes.
    """
    detail = _get_json(f"{base}/api/v1/plugins/{namespace}/{name}")
    latest = detail.get("latest")
    if not latest or not latest.get("spec"):
        raise GenError(f"{namespace}/{name} has no published version with a spec")
    spec = latest["spec"]

    docs = _get_json(f"{base}/api/v1/plugins/{namespace}/{name}/docs")
    files: dict[str, bytes] = {}
    for entry in docs.get("files", []):
        path = entry["path"]
        if "content" in entry:
            files[path] = entry["content"].encode("utf-8")
        else:
            # An image member: fetch its raw bytes from the asset route. The
            # stored path begins `docs/`; the asset route addresses it relative
            # to that prefix.
            rel = path[len("docs/") :] if path.startswith("docs/") else path
            files[path] = _get(f"{base}/api/v1/plugins/{namespace}/{name}/docs/assets/{rel}")
    return spec, files


# --------------------------------------------------------------------------- #
# Rendering (pure — fixture-testable, no network)
# --------------------------------------------------------------------------- #

# PNG/JPEG/GIF/WEBP magic-byte prefixes. SVG and every non-raster is rejected —
# a committed SVG ships as active content to the docs site.
_RASTER_MAGIC: tuple[bytes, ...] = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
)


def sniff_raster(data: bytes) -> bool:
    """True only when the bytes begin with a known raster magic (WEBP via RIFF…WEBP)."""
    if any(data.startswith(sig) for sig in _RASTER_MAGIC):
        return True
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def strip_front_matter(text: str) -> tuple[dict, str]:
    """Split a page into ``(front_matter_dict, body)``; empty dict when absent."""
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        import yaml

        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[m.end() :]


def _fm_value(value: object) -> str:
    """A front-matter scalar rendered as a safely double-quoted YAML string.

    ``json.dumps`` of a ``str`` is a valid double-quoted YAML flow scalar (a JSON
    string is a subset of YAML's), so any embedded quote, backslash, or newline is
    escaped rather than breaking the front matter. This covers the main page's
    title/description, which come from the marketplace SPEC and never pass
    ``validate_docs`` — a hostile third-party ``display_name`` cannot emit broken
    YAML here."""
    return json.dumps(str(value))


def mdx_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("{", "&#123;").replace("}", "&#125;")


def _anchor(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def group_label_for(spec: dict) -> str:
    """The nav group label for a listing, from its FIRST provides item kind."""
    provides = spec.get("provides") or []
    if not provides:
        raise GenError(f"{spec.get('namespace')}/{spec.get('name')}: spec provides no items")
    kind = provides[0]["kind"]
    label = KIND_GROUP_LABELS.get(kind)
    if label is None:
        raise GenError(
            f"{spec['namespace']}/{spec['name']}: first item kind {kind!r} is not in the "
            f"fixed nav label table — add its group mapping when this listing is ruled in"
        )
    return label


def render_page(spec: dict, body: str) -> str:
    """The full plugin page: GENERATED header (from the spec) + the docs body."""
    ns, name = spec["namespace"], spec["name"]
    title = spec.get("display_name") or name
    description = spec.get("description", "")
    first_kind = spec["provides"][0]["kind"]
    kind_label = _ITEM_KIND_LABELS.get(first_kind, first_kind)
    perms = spec.get("permissions") or {}

    lines: list[str] = [
        "---",
        f"title: {_fm_value(title)}",
        f"description: {_fm_value(description)}",
        "---",
        "",
        "{/* GENERATED by scripts/gen_plugins.py from the marketplace — do not edit. */}",
        "",
        f"<Info>`{mdx_cell(kind_label)}` plugin · listing `{ns}/{name}`"
        + (" · premium" if spec.get("premium") else "")
        + "</Info>",
        "",
        "## Install",
        "",
        "```bash",
        f"tai plugins install {spec['package']}",
        "```",
        "",
        "## Permissions",
        "",
        "| Capability | Declared |",
        "|---|---|",
        f"| Network | {'yes' if perms.get('network') else 'no'} |",
        f"| Subprocess | {'yes' if perms.get('subprocess') else 'no'} |",
        f"| Filesystem | {'yes' if perms.get('filesystem') else 'no'} |",
        "",
        "## Provides",
        "",
    ]
    for item in spec["provides"]:
        item_label = _ITEM_KIND_LABELS.get(item["kind"], item["kind"])
        lines.append(f"### {mdx_cell(item['name'])} {{#{_anchor(item['name'])}}}")
        lines.append("")
        lines.append(f"`{mdx_cell(item_label)}` — {mdx_cell(item.get('description', ''))}")
        lines.append("")

    body = body.strip()
    if body:
        lines.append(body)
        lines.append("")
    return "\n".join(lines) + "\n"


def rewrite_image_refs(body: str, ns: str, name: str) -> str:
    """Rewrite relative docs image references to the committed ``/plugins/images`` path."""
    prefix = f"/plugins/images/{ns}-{name}/"

    def repl(m: re.Match) -> str:
        target = m.group(2)
        filename = target.rsplit("/", 1)[-1]
        return f"{m.group(1)}{prefix}{filename}"

    return _IMG_REF_RE.sub(repl, body)


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def process_listing(spec: dict, files: dict[str, bytes]) -> dict:
    """Validate + render one listing. Returns a plan dict of files to write.

    Keys: ``main_slug``, ``pages`` ({slug: mdx}), ``images`` ({relpath: bytes}),
    ``group`` (nav label), ``registry`` (the snapshot row)."""
    ns, name = spec["namespace"], spec["name"]
    first_party = ns == "tai42"

    # Defense in depth: re-run the canonical validator on the fetched payload.
    try:
        validate_docs_payload(files, first_party=first_party)
    except DocsValidationError as exc:
        raise GenError(f"{ns}/{name}: docs failed the canonical contract — {exc}") from exc

    # Re-sniff every image raster-only before it can be committed.
    images: dict[str, bytes] = {}
    for path, data in files.items():
        if "/images/" in path:
            if not sniff_raster(data):
                raise GenError(f"{ns}/{name}: docs asset {path!r} is not a raster image — refusing to commit it")
            images[f"{ns}-{name}/{path.rsplit('/', 1)[-1]}"] = data

    index_key = "docs/index.mdx"
    if index_key not in files:
        raise GenError(f"{ns}/{name}: docs tree has no index.mdx")
    _, index_body = strip_front_matter(files[index_key].decode("utf-8"))
    index_body = rewrite_image_refs(index_body, ns, name)

    pages: dict[str, str] = {f"plugins/{ns}/{name}": render_page(spec, index_body)}

    # Extra .mdx pages become nested sub-pages under the plugin.
    extra_slugs: list[str] = []
    for path in sorted(files):
        if path == index_key or not path.endswith(".mdx"):
            continue
        rel = path[len("docs/") :][: -len(".mdx")]
        fm, body = strip_front_matter(files[path].decode("utf-8"))
        body = rewrite_image_refs(body, ns, name)
        slug = f"plugins/{ns}/{name}/{rel}"
        page = ["---", f"title: {_fm_value(fm.get('title', rel))}"]
        page += [f"description: {_fm_value(fm.get('description', ''))}", "---", "", body.strip(), ""]
        pages[slug] = "\n".join(page) + "\n"
        extra_slugs.append(slug)

    registry_row = {
        "namespace": ns,
        "name": name,
        "package": spec["package"],
        "premium": bool(spec.get("premium", False)),
        "items": [
            {"kind": it["kind"], "name": it["name"], "module": it.get("module"), "description": it["description"]}
            for it in spec["provides"]
        ],
    }
    return {
        "main_slug": f"plugins/{ns}/{name}",
        "extra_slugs": extra_slugs,
        "title": spec.get("display_name") or name,
        "pages": pages,
        "images": images,
        "group": group_label_for(spec),
        "registry": registry_row,
    }


def render_index(plans: list[dict]) -> str:
    """The Plugins section landing (generated): links the kind groups."""
    by_group: dict[str, int] = {}
    for plan in plans:
        by_group[plan["group"]] = by_group.get(plan["group"], 0) + 1
    lines = [
        "---",
        'title: "Plugins"',
        'description: "Every plugin listed on the marketplace, grouped by what it provides."',
        'icon: "puzzle-piece"',
        "---",
        "",
        "{/* GENERATED by scripts/gen_plugins.py from the marketplace — do not edit. */}",
        "",
        f"Every listed plugin, grouped by what its first item provides — {len(plans)} "
        f"across {len(by_group)} groups. Each plugin page carries its install line, "
        "declared permissions, the items it provides, and the author's own documentation.",
        "",
        "<CardGroup cols={2}>",
    ]
    for group in GROUP_ORDER:
        if group not in by_group:
            continue
        count = by_group[group]
        icon = GROUP_ICONS.get(group, "puzzle-piece")
        lines.append(f'  <Card title="{group}" icon="{icon}">')
        lines.append(f"    {count} {'plugin' if count == 1 else 'plugins'}.")
        lines.append("  </Card>")
    lines.append("</CardGroup>")
    return "\n".join(lines) + "\n"


def build_nav_group(plans: list[dict]) -> dict:
    """The top-level ``Plugins`` docs.json group: kind subgroups in fixed order."""
    grouped: dict[str, list[dict]] = {}
    for plan in sorted(plans, key=lambda p: p["main_slug"]):
        grouped.setdefault(plan["group"], []).append(plan)

    subgroups: list[dict] = []
    for label in GROUP_ORDER:
        if label not in grouped:
            continue
        pages: list = []
        for plan in grouped[label]:
            if plan["extra_slugs"]:
                pages.append({"group": plan["title"], "pages": [plan["main_slug"], *plan["extra_slugs"]]})
            else:
                pages.append(plan["main_slug"])
        subgroups.append({"group": label, "icon": GROUP_ICONS.get(label, "puzzle-piece"), "pages": pages})
    return {"group": "Plugins", "icon": "puzzle-piece", "pages": ["plugins/index"], "groups": subgroups}


def write_nav(group: dict) -> None:
    """Install the Plugins group in docs.json's Docs tab (own-group rewrite)."""
    data = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    for tab in data["navigation"]["tabs"]:
        if tab.get("tab") != "Docs":
            continue
        groups = tab["groups"]
        for i, existing in enumerate(groups):
            if existing.get("group") == "Plugins":
                groups[i] = group
                break
        else:
            groups.append(group)
        DOCS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    raise GenError("docs.json: Docs tab not found")


def prune_stale_outputs() -> None:
    """Clear gen_plugins' prior owned output so a delisted or renamed plugin leaves
    nothing on disk — its now-nav-less page would else trip check_docs' orphan check
    and wedge the automated regen PR. Mirrors the sibling generators' clear-before-write
    step, generalized to this section's nested layout.

    Scoped STRICTLY to the ``plugins/`` tree this generator owns: every committed
    ``plugins/**/*.mdx`` (main pages AND ``{ns}/{name}/{page}.mdx`` sub-pages) except
    the freshly-rewritten ``plugins/index.mdx``, plus every per-plugin image subtree
    under ``plugins/images/``. Nothing outside ``plugins/`` is touched, and
    ``plugins/_registry.json`` (not an ``.mdx``) is left for its own rewrite. The
    current outputs are written back immediately after, so this is a no-op on drift
    for an unchanged registry (prune the 25 + rewrite the same 25 is byte-identical)."""
    index_page = PLUGINS_DIR / "index.mdx"
    for existing in PLUGINS_DIR.rglob("*.mdx"):
        if existing != index_page:
            existing.unlink()
    if IMAGES_DIR.is_dir():
        for child in IMAGES_DIR.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def write_outputs(plans: list[dict]) -> None:
    """Write pages, images, _registry.json, index, and nav. Caller has validated."""
    prune_stale_outputs()
    for plan in plans:
        for slug, mdx in plan["pages"].items():
            out = DOCS_ROOT / f"{slug}.mdx"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(mdx, encoding="utf-8")
        for rel, data in plan["images"].items():
            img = IMAGES_DIR / rel
            img.parent.mkdir(parents=True, exist_ok=True)
            img.write_bytes(data)

    (PLUGINS_DIR / "index.mdx").write_text(render_index(plans), encoding="utf-8")

    registry = {
        "_comment": (
            "Snapshot of the marketplace plugin registry (listings + item rows), emitted by "
            "gen_plugins.py. The offline consumers (gen_toolbox_table, gen_capability_map, "
            "check_docs_refs) read this instead of the network."
        ),
        "listings": [
            plan["registry"]
            for plan in sorted(plans, key=lambda p: (p["registry"]["namespace"], p["registry"]["name"]))
        ],
    }
    REGISTRY_OUT.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    write_nav(build_nav_group(plans))


def main() -> int:
    base = _base_url()
    try:
        refs = fetch_listing_refs(base)
        plans: list[dict] = []
        for ns, name in refs:
            spec, files = fetch_listing(base, ns, name)
            plans.append(process_listing(spec, files))
    except GenError as exc:
        print(f"gen_plugins: {exc}", file=sys.stderr)
        return 1

    write_outputs(plans)
    print(f"gen_plugins: wrote {len(plans)} plugin pages + _registry.json + nav")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
