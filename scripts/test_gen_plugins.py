#!/usr/bin/env python3
"""Tests for the Plugins-section generator — fixture-driven (no network).

The generator can only RUN against a live marketplace; these tests drive its pure
rendering/validation/nav functions against fixture API payloads, following the
harness style of the other generator tests::

    uv run pytest scripts/test_gen_plugins.py

Guarantees: header + install line + permissions table + per-item anchors render;
image references rewrite to the committed path; the canonical validator refuses
unsafe third-party mdx; a non-raster image is refused; an unmapped first-item kind
is a loud failure naming it; an empty enumeration is a loud nonzero exit; the nav
group is built grouped by first-item kind.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_plugins  # noqa: E402

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def _spec(namespace: str = "tai42", first_kind: str = "tool") -> dict:
    return {
        "spec_version": 1,
        "namespace": namespace,
        "name": "demo",
        "display_name": "Demo Plugin",
        "package": "tai42-demo",
        "description": "A demo plugin.",
        "premium": False,
        "permissions": {"network": True, "subprocess": False, "filesystem": False},
        "provides": [
            {"kind": first_kind, "name": "do_thing", "module": "tai42_demo.tools.do", "description": "Do a thing."},
            {"kind": "extension", "name": "wrap_it", "module": "tai42_demo.ext.wrap", "description": "Wrap a tool."},
        ],
    }


def _files(body: str = "Body text ![pic](./images/pic.png)\n", image: bytes = _PNG) -> dict[str, bytes]:
    index = f'---\ntitle: "Demo"\ndescription: "A demo."\n---\n\n{body}'.encode()
    return {"docs/index.mdx": index, "docs/images/pic.png": image}


# --- happy path ------------------------------------------------------------


def test_process_listing_renders_header_and_anchors() -> None:
    plan = gen_plugins.process_listing(_spec(), _files())
    page = plan["pages"]["plugins/tai42/demo"]

    assert plan["main_slug"] == "plugins/tai42/demo"
    assert plan["group"] == "Tools"
    assert 'title: "Demo Plugin"' in page
    assert "tai plugins install tai42-demo" in page
    assert "| Network | yes |" in page
    assert "| Subprocess | no |" in page
    # Per-item anchors.
    assert "### do_thing {#do-thing}" in page
    assert "### wrap_it {#wrap-it}" in page
    # Item descriptions verbatim.
    assert "Do a thing." in page
    # Image reference rewritten + the raster carried for commit.
    assert "/plugins/images/tai42-demo/pic.png" in page
    assert "tai42-demo/pic.png" in plan["images"]
    # Registry snapshot row.
    assert plan["registry"]["package"] == "tai42-demo"
    assert [i["name"] for i in plan["registry"]["items"]] == ["do_thing", "wrap_it"]
    print("  happy path: header, anchors, image rewrite, registry row")


def test_item_group_tag_rendered_when_present() -> None:
    """A provides item's group tag renders inline in its badge; ungrouped items are untouched."""
    spec = _spec()
    spec["provides"][0]["group"] = "core"  # grouped
    # second item has no `group` key at all — older data, ungrouped
    page = gen_plugins.process_listing(spec, _files())["pages"]["plugins/tai42/demo"]

    # Grouped item carries the tag in the established ` · ` badge idiom.
    assert "`Tool` · group `core` — Do a thing." in page
    # Ungrouped item renders exactly as today — no group tag, no empty noise.
    assert "`Extension` — Wrap a tool." in page
    print("  group tag: grouped item tagged, ungrouped item unchanged")


def test_absent_and_null_group_are_ungrouped() -> None:
    """An absent key and an explicit null both mean ungrouped — never a failure."""
    spec = _spec()
    spec["provides"][0]["group"] = None  # explicit null
    page = gen_plugins.process_listing(spec, _files())["pages"]["plugins/tai42/demo"]
    assert "`Tool` — Do a thing." in page
    assert "group `" not in page
    print("  group tag: absent key and null both ungrouped")


def test_malformed_group_fails_loud() -> None:
    """A present-but-malformed group value is a loud failure naming the item."""
    for bad in ("", "   ", 7, ["core"]):
        spec = _spec()
        spec["provides"][0]["group"] = bad
        with pytest.raises(gen_plugins.GenError) as exc:
            gen_plugins.process_listing(spec, _files())
        assert "malformed group tag" in str(exc.value)
        assert "do_thing" in str(exc.value)
    print("  group tag: malformed value fails loud naming the item")


def test_image_ref_rewrite_variants() -> None:
    out = gen_plugins.rewrite_image_refs("![a](images/x.png) ![b](./docs/images/y.png)", "tai42", "demo")
    assert "/plugins/images/tai42-demo/x.png" in out
    assert "/plugins/images/tai42-demo/y.png" in out


# --- refusals --------------------------------------------------------------


def test_third_party_unsafe_mdx_refused() -> None:
    """A third-party payload with a raw HTML tag is refused by the canonical validator."""
    with pytest.raises(gen_plugins.GenError) as exc:
        gen_plugins.process_listing(_spec(namespace="acme"), _files(body="<div>raw html</div>\n"))
    # Assert the SAFE-SUBSET reason, not merely GenError: a kit-less env would raise
    # GenError for the wrong reason (kit unimportable), which must not pass here.
    assert "not permitted in third-party docs" in str(exc.value)
    print("  refusal: unsafe third-party mdx")


def test_non_raster_image_refused() -> None:
    """An asset whose bytes are not a raster (an SVG) is refused before commit."""
    with pytest.raises(gen_plugins.GenError) as exc:
        gen_plugins.process_listing(_spec(), _files(body="Body.\n", image=b"<svg xmlns='...'></svg>"))
    # Assert the RASTER guard fired, not the kit-unimportable path (wrong-reason pass).
    assert "not a raster image" in str(exc.value)
    print("  refusal: non-raster image")


def test_unmapped_first_item_kind_fails_loud() -> None:
    with pytest.raises(gen_plugins.GenError) as exc:
        gen_plugins.group_label_for(_spec(first_kind="router"))
    assert "router" in str(exc.value)
    print("  fail-loud: unmapped first-item kind names it")


def test_empty_enumeration_fails_loud(monkeypatch) -> None:
    monkeypatch.setattr(gen_plugins, "_get_json", lambda url: {"items": []})
    with pytest.raises(gen_plugins.GenError):
        gen_plugins.fetch_listing_refs("https://mp.example")
    print("  fail-loud: empty listing set")


def test_sniff_raster() -> None:
    assert gen_plugins.sniff_raster(_PNG)
    assert gen_plugins.sniff_raster(b"RIFF____WEBP____")
    assert not gen_plugins.sniff_raster(b"<svg></svg>")


# --- nav -------------------------------------------------------------------


def test_build_nav_group_by_kind() -> None:
    tool_plan = gen_plugins.process_listing(_spec(), _files(body="Body.\n"))
    id_spec = _spec(first_kind="identity")
    id_spec["name"] = "accounts-x"
    id_plan = gen_plugins.process_listing(id_spec, _files(body="Body.\n"))

    nav = gen_plugins.build_nav_group([tool_plan, id_plan])
    assert nav["group"] == "Plugins"
    # Sub-groups nest INSIDE pages (the docs.json schema has no ``groups`` key
    # on a group object), after the landing page.
    assert nav["pages"][0] == "plugins/index"
    subgroups = nav["pages"][1:]
    assert "groups" not in nav
    labels = [sub["group"] for sub in subgroups]
    assert "Tools" in labels
    assert "Identity" in labels
    # Tools precedes Identity per the fixed GROUP_ORDER.
    assert labels.index("Tools") < labels.index("Identity")
    tools = next(s for s in subgroups if s["group"] == "Tools")
    assert "plugins/tai42/demo" in tools["pages"]
    print("  nav: grouped by first-item kind in fixed order")


# --- prune -----------------------------------------------------------------


def test_write_outputs_prunes_delisted_plugin(tmp_path, monkeypatch) -> None:
    """A delisted plugin's stale page + image subtree are pruned; current output survives.

    Drives the real write path over a redirected output tree so nothing touches the
    committed section. Seeds a STALE `plugins/tai42/deleted-plugin.mdx` and a stale
    image dir, runs the generator over a registry that omits them, and asserts the
    stale output is GONE while the current page/image/index remain.
    """
    docs_root = tmp_path
    plugins_dir = docs_root / "plugins"
    images_dir = plugins_dir / "images"
    (plugins_dir / "tai42").mkdir(parents=True)

    stale_page = plugins_dir / "tai42" / "deleted-plugin.mdx"
    stale_page.write_text("stale — delisted plugin\n", encoding="utf-8")
    stale_img_dir = images_dir / "tai42-deleted-plugin"
    stale_img_dir.mkdir(parents=True)
    (stale_img_dir / "old.png").write_bytes(_PNG)

    # Minimal docs.json carrying the Plugins group the nav writer rewrites in place.
    docs_json = docs_root / "docs.json"
    docs_json.write_text(
        json.dumps({"navigation": {"tabs": [{"tab": "Docs", "groups": [{"group": "Plugins"}]}]}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(gen_plugins, "DOCS_ROOT", docs_root)
    monkeypatch.setattr(gen_plugins, "PLUGINS_DIR", plugins_dir)
    monkeypatch.setattr(gen_plugins, "IMAGES_DIR", images_dir)
    monkeypatch.setattr(gen_plugins, "REGISTRY_OUT", plugins_dir / "_registry.json")
    monkeypatch.setattr(gen_plugins, "DOCS_JSON", docs_json)

    plan = gen_plugins.process_listing(_spec(), _files())
    gen_plugins.write_outputs([plan])

    # The delisted plugin's page + image subtree are gone.
    assert not stale_page.exists()
    assert not stale_img_dir.exists()
    # The current plugin page, its image, and the rewritten index survive.
    assert (plugins_dir / "tai42" / "demo.mdx").exists()
    assert (images_dir / "tai42-demo" / "pic.png").exists()
    assert (plugins_dir / "index.mdx").exists()
    # _registry.json is rewritten (never pruned).
    assert (plugins_dir / "_registry.json").exists()
    print("  prune: delisted plugin page + images removed, current output kept")


def main() -> int:
    print("test_gen_plugins:")
    test_process_listing_renders_header_and_anchors()
    test_item_group_tag_rendered_when_present()
    test_absent_and_null_group_are_ungrouped()
    test_malformed_group_fails_loud()
    test_image_ref_rewrite_variants()
    test_third_party_unsafe_mdx_refused()
    test_non_raster_image_refused()
    test_unmapped_first_item_kind_fails_loud()
    test_sniff_raster()
    test_build_nav_group_by_kind()
    print("test_gen_plugins: OK (run under pytest for the monkeypatch case)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
