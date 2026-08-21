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


def _descriptor_spec() -> dict:
    """A descriptor-only listing: ``package`` null, one oauth connector item whose
    provider descriptor names its client credential env vars."""
    return {
        "spec_version": 1,
        "namespace": "tai42",
        "name": "connector-acme",
        "display_name": "Acme connector",
        "package": None,
        "description": "Connect to Acme.",
        "premium": False,
        "permissions": {"network": True, "subprocess": False, "filesystem": False},
        "provides": [
            {
                "kind": "connector",
                "name": "acme",
                "description": "Acme OAuth connector.",
                "provider": {
                    "id": "acme",
                    "kind": "oauth",
                    "origin": "system",
                    "client_id_env": "CONNECTORS_ACME_CLIENT_ID",
                    "client_secret_env": "CONNECTORS_ACME_CLIENT_SECRET",
                },
            }
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


def test_descriptor_listing_install_line_and_registry() -> None:
    """A descriptor-only listing (package null) installs by ref with env flags, and
    its registry row carries a null package rather than crashing on a missing key."""
    plan = gen_plugins.process_listing(_descriptor_spec(), _files(body="Body.\n"))
    page = plan["pages"]["plugins/tai42/connector-acme"]

    # Install by namespace/name ref, never a null package name.
    assert "tai plugins install tai42/connector-acme" in page
    assert "None" not in page.split("## Permissions")[0]
    # EVERY var gets its VALUE via --env; the secret takes an ADDITIONAL bare
    # --secret mark (never `--secret NAME=...`, which passes a value to a
    # mark-only flag).
    assert "--env CONNECTORS_ACME_CLIENT_ID=..." in page
    assert "--env CONNECTORS_ACME_CLIENT_SECRET=..." in page
    assert "--secret CONNECTORS_ACME_CLIENT_SECRET" in page
    assert "--secret CONNECTORS_ACME_CLIENT_SECRET=..." not in page
    # The registry snapshot row emits a null package (consumers skip it).
    assert plan["registry"]["package"] is None
    # It shelves under the connect group, like a package-delivered connector.
    assert plan["group"] == "Connect outside systems"
    print("  descriptor: ref install line + env/secret flags + null registry package")


def test_install_command_package_and_descriptor() -> None:
    """install_command uses the distribution when present, the ref otherwise; a
    descriptor supplies every value via --env and marks the secret with a BARE
    --secret (the mark-only flag, no =VALUE)."""
    assert gen_plugins.install_command(_spec()) == "tai plugins install tai42-demo"
    assert gen_plugins.install_command(_descriptor_spec()) == (
        "tai plugins install tai42/connector-acme "
        "--env CONNECTORS_ACME_CLIENT_ID=... --env CONNECTORS_ACME_CLIENT_SECRET=... "
        "--secret CONNECTORS_ACME_CLIENT_SECRET"
    )
    print("  install_command: package by name, descriptor by ref, --env values + bare --secret")


def test_install_command_missing_package_key() -> None:
    """A spec that OMITS ``package`` entirely (not just ``package: null``) is a
    descriptor: install_command reads it with .get and never KeyErrors."""
    spec = _descriptor_spec()
    del spec["package"]
    cmd = gen_plugins.install_command(spec)
    assert cmd.startswith("tai plugins install tai42/connector-acme")
    assert "--env CONNECTORS_ACME_CLIENT_ID=..." in cmd
    assert "--secret CONNECTORS_ACME_CLIENT_SECRET" in cmd
    print("  install_command: absent package key handled as descriptor (no KeyError)")


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


def test_hand_authored_page_survives_prune(tmp_path, monkeypatch) -> None:
    """A HAND_AUTHORED_PAGES entry (the descriptor-authoring guide) is NOT a
    generated plugin page and must survive prune_stale_outputs — guards against a
    keep-set regression silently deleting a hand-committed page under plugins/."""
    plugins_dir = tmp_path / "plugins"
    images_dir = plugins_dir / "images"
    plugins_dir.mkdir(parents=True)

    (plugins_dir / "index.mdx").write_text("landing\n", encoding="utf-8")
    stale_page = plugins_dir / "tai42" / "old.mdx"
    stale_page.parent.mkdir(parents=True)
    stale_page.write_text("stale\n", encoding="utf-8")
    # Every hand-authored page the generator owns-not is seeded and must remain.
    for name in gen_plugins.HAND_AUTHORED_PAGES:
        (plugins_dir / name).write_text("hand-authored guide\n", encoding="utf-8")

    monkeypatch.setattr(gen_plugins, "PLUGINS_DIR", plugins_dir)
    monkeypatch.setattr(gen_plugins, "IMAGES_DIR", images_dir)

    gen_plugins.prune_stale_outputs()

    assert not stale_page.exists()  # a generated plugin page is pruned
    assert (plugins_dir / "index.mdx").exists()  # the generator-owned landing survives
    for name in gen_plugins.HAND_AUTHORED_PAGES:
        assert (plugins_dir / name).exists(), f"hand-authored {name} was pruned"
    assert gen_plugins.HAND_AUTHORED_PAGES  # the set is non-empty (there is a page to protect)
    print("  prune: hand-authored pages survive, generated pages pruned")


def main() -> int:
    print("test_gen_plugins:")
    test_process_listing_renders_header_and_anchors()
    test_descriptor_listing_install_line_and_registry()
    test_install_command_package_and_descriptor()
    test_install_command_missing_package_key()
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
