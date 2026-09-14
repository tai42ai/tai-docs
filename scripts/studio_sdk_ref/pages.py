"""Assemble the reference pages, the index landing page, and the slug order.

Renders every category page into memory (no filesystem writes), computes each
export's cross-link location so references resolve across pages, and builds the
CardGroup index page. Fails loud when no public export is found.
"""

from __future__ import annotations

from studio_sdk_ref import config
from studio_sdk_ref.collect import category_for, enumerate_exports, index_by_id
from studio_sdk_ref.errors import GenerationError
from studio_sdk_ref.render import anchor_for, frontmatter, mdx_escape_prose, render_symbol
from studio_sdk_ref.typestr import init_alias_context


def build_reference(project: dict) -> tuple[dict[str, str], dict[str, list[str]], set[str]]:
    """Render every page into memory.

    Returns (slug -> mdx, slug -> rendered symbol names, all rendered names).
    Does not touch the filesystem. Raises GenerationError when no public export
    is found — the fail-loud guard against writing an empty reference."""
    id_index = index_by_id(project)
    exports = enumerate_exports(project)
    if not exports:
        raise GenerationError("no public exports found in the studio-sdk entry points")
    init_alias_context(project, exports)

    # Pass 1 — assign every export to a page and compute its location, so cross
    # references can link across pages.
    assigned: dict[str, list[tuple[dict, str]]] = {cat["slug"]: [] for cat in config.CATEGORIES}
    location: dict[str, tuple[str, str]] = {}
    for refl, module_name in exports:
        slug = category_for(refl, module_name)
        assigned[slug].append((refl, module_name))
        location[refl["name"]] = (slug, anchor_for(refl["name"]))

    # Pass 2 — render each non-empty category page.
    pages: dict[str, str] = {}
    page_symbols: dict[str, list[str]] = {}
    all_symbols: set[str] = set()

    for cat in config.CATEGORIES:
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
    for cat in config.CATEGORIES:
        slug = cat["slug"]
        if slug not in page_symbols:
            continue
        count = len(page_symbols[slug])
        noun = "export" if count == 1 else "exports"
        body.append(
            f'  <Card title="{cat["title"]}" icon="{cat["icon"]}" '
            f'href="/{config.NAV_PREFIX}/{slug}">\n'
            f"    {mdx_escape_prose(cat['description'])} ({count} {noun})\n"
            f"  </Card>"
        )
    body.append("</CardGroup>")
    return "\n".join(body) + "\n"


def _ordered_slugs(page_symbols: dict[str, list[str]]) -> list[str]:
    """Category slugs that were actually rendered, in CATEGORIES order."""
    return [cat["slug"] for cat in config.CATEGORIES if cat["slug"] in page_symbols]
