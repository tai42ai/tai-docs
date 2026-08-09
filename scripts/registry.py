#!/usr/bin/env python3
"""Read the committed ``plugins/_registry.json`` — the marketplace registry snapshot.

``gen_plugins.py`` emits this file (listings + item rows) on every successful
online regeneration; the offline consumers (``gen_toolbox_table``,
``gen_capability_map``, ``check_docs_refs``) read it here instead of the network,
so the drift gate never needs the marketplace. Absent or malformed = loud exit:
a consumer never silently degrades to an empty section.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
REGISTRY_PATH = DOCS_ROOT / "plugins" / "_registry.json"

# Every listing carries these; every item row carries {kind, name, module,
# description} (module null only for mcp-server rows).
_LISTING_FIELDS = ("namespace", "name", "package", "premium", "items")
_ITEM_FIELDS = ("kind", "name", "description")


def load_registry(path: Path = REGISTRY_PATH) -> list[dict]:
    """Return the registry's listings, validated for shape; loud exit otherwise."""
    if not path.is_file():
        print(
            f"registry: {path} is absent — run gen_plugins.py against the marketplace "
            f"to emit it (the offline consumers read this snapshot, never the network).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"registry: {path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    listings = doc.get("listings") if isinstance(doc, dict) else None
    if not isinstance(listings, list) or not listings:
        print(f"registry: {path} has no listings", file=sys.stderr)
        raise SystemExit(1)

    for i, listing in enumerate(listings):
        missing = [f for f in _LISTING_FIELDS if f not in listing]
        if missing:
            print(f"registry: listing #{i} missing fields: {', '.join(missing)}", file=sys.stderr)
            raise SystemExit(1)
        items = listing["items"]
        if not isinstance(items, list) or not items:
            print(
                f"registry: listing {listing['namespace']}/{listing['name']} has no items",
                file=sys.stderr,
            )
            raise SystemExit(1)
        for item in items:
            item_missing = [f for f in _ITEM_FIELDS if f not in item]
            if item_missing:
                print(
                    f"registry: an item of {listing['namespace']}/{listing['name']} "
                    f"missing fields: {', '.join(item_missing)}",
                    file=sys.stderr,
                )
                raise SystemExit(1)
    return listings
