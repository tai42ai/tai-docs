#!/usr/bin/env python3
"""Tests for the capability-map generator — fixture-driven::

    uv run pytest scripts/test_gen_capability_map.py

Guarantees: the fixed feature areas render; each one-liner is its source field
verbatim / name-derived; a missing OpenAPI summary is a loud failure naming the
route; a settings/agent source with no description falls back to the deterministic
label; ordering is deterministic; an empty agent registry renders an empty area
(never a loud failure).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_capability_map as gcm  # noqa: E402


def _openapi() -> dict:
    return {
        "paths": {
            "/api/agents": {"get": {"tags": ["agents"], "summary": "List every registered agent"}},
            "/api/tools": {"get": {"tags": ["tools"], "summary": "List every registered tool"}},
        }
    }


def _listings() -> list[dict]:
    return [
        {
            "namespace": "tai42",
            "name": "toolbox",
            "package": "tai42-toolbox",
            "premium": False,
            "items": [
                {
                    "kind": "tool",
                    "name": "generate_uuid",
                    "module": "tai42_toolbox.tools.u",
                    "description": "Generate a random UUID (version 4).",
                }
            ],
        }
    ]


def _settings() -> list[dict]:
    return [{"name": "redis_settings", "module": "tai42_kit.clients.redis"}]


# --- areas -----------------------------------------------------------------


def test_http_api_summary_verbatim_and_grouped() -> None:
    lines = "\n".join(gcm.render_http_api(_openapi()))
    assert "## HTTP API" in lines
    assert "### Agents" in lines
    assert "### Tools" in lines
    assert "List every registered agent" in lines
    assert "`GET /api/agents`" in lines


def test_http_api_missing_summary_fails_loud() -> None:
    bad = {"paths": {"/api/x": {"get": {"tags": ["x"], "summary": ""}}}}
    with pytest.raises(gcm.MapError) as exc:
        gcm.render_http_api(bad)
    assert "GET /api/x" in str(exc.value)


def test_plugins_description_verbatim_and_source() -> None:
    lines = "\n".join(gcm.render_plugins(_listings()))
    assert "## Plugins" in lines
    assert "Generate a random UUID (version 4)." in lines
    assert "/plugins/tai42/toolbox" in lines
    assert "`tai42_toolbox.tools.u`" in lines  # source-module anchor (non-core -> plain code)


def test_settings_name_derived_label_and_core_link() -> None:
    lines = "\n".join(gcm.render_settings(_settings()))
    # A name already ending in "settings" keeps a SINGLE suffix (no "settings settings").
    assert "Redis Settings (tai42_kit.clients.redis)" in lines
    # A tai42_kit module gets a monorepo hyperlink.
    assert "github.com/tai42ai/tai42/tree/main/core/kit" in lines


def test_settings_label_camelcase_and_suffix() -> None:
    groups = [
        {"name": "ContextOverflowSettings", "module": "tai42_kit.overflow"},
        {"name": "logging", "module": "tai42_kit.log"},
    ]
    lines = "\n".join(gcm.render_settings(groups))
    # CamelCase splits on case boundaries; the existing "Settings" suffix is not doubled.
    assert "Context Overflow Settings (tai42_kit.overflow)" in lines
    # A name without the suffix gets the single derived " settings".
    assert "Logging settings (tai42_kit.log)" in lines


def test_agents_extensions_empty_area_not_a_failure() -> None:
    lines = "\n".join(gcm.render_agents_extensions([], []))
    assert "## Agents & extensions" in lines
    assert "listed under Plugins" in lines


def test_agents_extensions_rows() -> None:
    agents = [{"name": "deep_agent", "description": "A deep agent."}]
    extensions = [{"name": "cache", "kind": "extension"}]
    lines = "\n".join(gcm.render_agents_extensions(agents, extensions))
    assert "A deep agent." in lines
    assert "Cache (extension)" in lines


def test_full_page_has_all_areas_and_ordering() -> None:
    page = gcm.render(_openapi(), _listings(), _settings(), [], [])
    for area in ("## HTTP API", "## Plugins", "## Settings", "## Agents & extensions"):
        assert area in page
    assert "## Channels" not in page  # R19: no Channels area
    # Deterministic area order.
    assert (
        page.index("## HTTP API")
        < page.index("## Plugins")
        < page.index("## Settings")
        < page.index("## Agents & extensions")
    )


# --- source-resolution loud-fail guards ------------------------------------


def test_load_openapi_absent_fails_loud(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gcm, "OPENAPI", tmp_path / "nope.json")
    with pytest.raises(gcm.MapError) as exc:
        gcm.load_openapi()
    assert "absent" in str(exc.value)


def test_load_settings_groups_no_env_fails_loud(monkeypatch) -> None:
    # A None entry in sys.modules makes the import raise ImportError, which the
    # source-resolution guard must re-raise LOUDLY as a MapError naming the env.
    monkeypatch.setitem(sys.modules, "tai42_kit.settings", None)
    with pytest.raises(gcm.MapError) as exc:
        gcm.load_settings_groups()
    assert "skeleton env" in str(exc.value)


def test_load_agents_extensions_no_skeleton_returns_empty(monkeypatch) -> None:
    # The ONLY silenced condition: the skeleton isn't importable (a bare regen env
    # with no registry to read) -> the area renders empty, never a failure.
    monkeypatch.setitem(sys.modules, "tai42_skeleton.app", None)
    assert gcm.load_agents_extensions() == ([], [])


def test_load_agents_extensions_unexpected_fails_loud(monkeypatch) -> None:
    # Any failure reaching the app or a facet is LOUD, not a silent empty area.
    import types

    parent = types.ModuleType("tai42_skeleton")
    app_mod = types.ModuleType("tai42_skeleton.app")

    class _BoomInstance:
        @property
        def app(self):
            raise RuntimeError("kaboom")

    app_mod.instance = _BoomInstance()
    monkeypatch.setitem(sys.modules, "tai42_skeleton", parent)
    monkeypatch.setitem(sys.modules, "tai42_skeleton.app", app_mod)
    with pytest.raises(gcm.MapError) as exc:
        gcm.load_agents_extensions()
    assert "kaboom" in str(exc.value)


def main() -> int:
    print("test_gen_capability_map:")
    test_http_api_summary_verbatim_and_grouped()
    test_http_api_missing_summary_fails_loud()
    test_plugins_description_verbatim_and_source()
    test_settings_name_derived_label_and_core_link()
    test_settings_label_camelcase_and_suffix()
    test_agents_extensions_empty_area_not_a_failure()
    test_agents_extensions_rows()
    test_full_page_has_all_areas_and_ordering()
    print("test_gen_capability_map: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
