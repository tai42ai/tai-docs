#!/usr/bin/env python3
"""First-party plugin discovery and settings-module import.

Shared by the settings-reference generator and the reference drift-check.

Both tools must read a deployment's plugin settings the SAME way a live server
does — a plugin registers its settings groups by importing the modules its
descriptor (``tai-plugin.yml``) lists in ``provides[].module`` (the same modules
the skeleton's component-import lifecycle imports at boot) — so the generated
reference and the drift-check never disagree on which groups a bundled plugin
registers.

Run where ``tai42_skeleton`` / ``tai42_kit`` and the plugin packages resolve (the
tai42-skeleton virtualenv synced with ``--all-packages``); a plugin package that
is not installed simply is not discovered.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tai42_contract.app import tai42_app
from tai42_contract.plugins.bindings import PluginItemKind
from tai42_contract.plugins.spec import PluginSpec
from tai42_kit.plugins import PLUGIN_SPEC_FILENAME, parse_plugin_spec
from tai42_kit.settings import TaiBaseSettings, registered_settings
from tai42_skeleton.app.server import TaiMCP

# First-party distributions carry this distribution-name prefix.
_FIRST_PARTY_DIST_PREFIX = "tai42-"

# The single-module manifest slots (``_import_core_slots``). Their
# ``provides[].module`` is not imported DIRECTLY: the top-level package (imported
# for every plugin below) already covers what these slots need — storage's
# provided module IS the top level, and arq/sandbox import their provided submodule
# from ``__init__`` — and each plugin's own ``settings.py`` (also imported below)
# holds its settings group. Importing the provided module directly can eagerly
# construct the live provider; monitoring-langfuse's ``register`` module raises
# without runtime credentials.
_SCALAR_SLOT_KINDS = frozenset(
    {PluginItemKind.BACKEND, PluginItemKind.STORAGE, PluginItemKind.MONITORING, PluginItemKind.SANDBOX}
)


@dataclass(frozen=True)
class PluginInfo:
    """One installed first-party plugin, located WITHOUT importing plugin code.

    It is located from its packaged descriptor.
    ``modules`` is the import sequence whose side-effect registers the plugin's
    settings groups: the top-level package first, then each additive
    ``provides[].module`` the descriptor lists (the modules a live deployment
    imports through ``_import_tool_modules`` / ``_import_extension_modules`` and the
    other additive-role importers), then the plugin's own ``settings`` modules —
    the source of a scalar-slot provider's settings group, whose provided module is
    not imported directly (the top-level package covers it; importing it directly
    can eagerly construct the live provider). All deduped, order preserved; a data
    item (``mcp-server`` / ``connector``) carries no ``module`` and contributes
    none.
    """

    dist_name: str
    top_level: str
    spec: PluginSpec
    modules: tuple[str, ...]


def discover_plugins() -> dict[str, PluginInfo]:
    """Every installed first-party (``tai42-``) plugin, keyed by distribution name.

    Covers each plugin that ships a packaged ``tai-plugin.yml``.
    Side-effect free: it locates the descriptor beside each distribution's
    top-level import package (the same ``importlib.resources`` / spec locator the
    skeleton mount map uses) and reads it off disk, importing no plugin code (a
    plugin registers providers/routes at import, which needs a bound app).
    """
    plugins: dict[str, PluginInfo] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"] or ""
        if not name.startswith(_FIRST_PARTY_DIST_PREFIX):
            continue
        top_level_txt = dist.read_text("top_level.txt") or ""
        for top_level in top_level_txt.split():
            try:
                module_spec = importlib.util.find_spec(top_level)
            except (ImportError, ValueError):
                module_spec = None
            if module_spec is None or not module_spec.submodule_search_locations:
                continue
            for location in module_spec.submodule_search_locations:
                spec_path = Path(location) / PLUGIN_SPEC_FILENAME
                if not spec_path.is_file():
                    continue
                plugin_spec = parse_plugin_spec(spec_path.read_bytes(), source=str(spec_path))
                provided = [
                    item.module for item in plugin_spec.provides if item.module and item.kind not in _SCALAR_SLOT_KINDS
                ]
                settings_modules = [
                    ".".join([top_level, *settings_file.relative_to(location).with_suffix("").parts])
                    for settings_file in sorted(Path(location).rglob("settings.py"))
                ]
                modules = tuple(dict.fromkeys([top_level, *provided, *settings_modules]))
                plugins.setdefault(name, PluginInfo(name, top_level, plugin_spec, modules))
                break
    return plugins


def import_plugin_settings(plugins: Iterable[PluginInfo]) -> None:
    """Import each plugin's descriptor modules so its settings groups register.

    A plugin registers providers/routes onto the ``tai42_app`` handle at import,
    so a fresh app is bound as the sink before each plugin — this both satisfies
    those import-time registrations and isolates a scalar slot (e.g. the single
    sandbox provider) so two plugins claiming it never collide. A route-carrying
    module (a ``router`` / ``channel`` item) reads its declared mount base at
    import, so it is imported under its :class:`MountBinding` from the plugin's own
    descriptor — the same binding the skeleton's component-import lifecycle carries
    — while every other module imports plainly. A plugin whose every provided item
    is kind ``mcp-server`` declares no ``contract`` and registers no platform
    settings group, so it is skipped.

    A missing module ABORTS the run loudly, naming the plugin, the module, and the
    missing name: the published reference must render every bundled plugin's groups,
    so a module the environment cannot import is a broken environment, never a
    silently dropped group. Any other exception propagates and aborts the run too.
    """
    from tai42_skeleton.access_control.settings import access_control_settings
    from tai42_skeleton.app.mount_map import bind_module, build_mount_map

    reserved = access_control_settings().reserved_public_pin_prefixes
    for info in plugins:
        if info.spec.contract is None:
            continue
        tai42_app.bind(TaiMCP(name="Tai"))
        mount_map = build_mount_map(list(info.modules), reserved, dict)
        for module in info.modules:
            try:
                with bind_module(mount_map.get(module)):
                    importlib.import_module(module)
            except ModuleNotFoundError as exc:
                raise ModuleNotFoundError(
                    f"{info.dist_name}: importing {module} failed — missing module {exc.name!r}; "
                    "the settings reference needs every bundled plugin's modules importable "
                    "(run from the monorepo skeleton environment: cd tai42/core/skeleton && "
                    "uv sync --all-packages --all-extras)"
                ) from exc


def _all_settings_subclasses() -> list[type[TaiBaseSettings]]:
    """Every registered ``TaiBaseSettings`` subclass, walked recursively.

    ``type.__subclasses__`` reports only direct subclasses, so an intermediate
    base (e.g. the kit's ``SandboxDispatchSettings``) would hide a plugin's own
    group; the recursion reaches every concrete leaf.
    """
    seen: dict[str, type[TaiBaseSettings]] = {}

    def walk(cls: type[TaiBaseSettings]) -> None:
        for sub in cls.__subclasses__():
            key = f"{sub.__module__}.{sub.__qualname__}"
            if key not in seen:
                seen[key] = sub
                walk(sub)

    walk(TaiBaseSettings)
    return list(seen.values())


@dataclass(frozen=True)
class BundledEnvNamespaces:
    """The env-var namespaces a set of bundled plugins own.

    Derived from the plugins' registered settings groups.
    ``prefixes`` are the non-empty ``env_prefix`` values those groups declare (a
    plugin's namespace). ``env_vars`` are the exact variables of any group that
    declares an EMPTY prefix — an empty prefix names no namespace of its own, so
    matching it as a prefix would claim every env key; its fields are matched
    exactly instead.
    """

    prefixes: frozenset[str]
    env_vars: frozenset[str]

    def owns(self, key: str) -> bool:
        """Whether ``key`` falls in a bundled plugin's env namespace."""
        return key in self.env_vars or any(key.startswith(prefix) for prefix in self.prefixes)


def bundled_env_namespaces(top_levels: set[str]) -> BundledEnvNamespaces:
    """The env namespaces owned by the registered settings groups in ``top_levels``.

    Covers each group whose module belongs to one of ``top_levels`` (the bundled
    plugins' top-level packages).
    The env prefix is read from each group's live model config; a group with an
    empty prefix contributes its exact field env vars, read from the registry
    snapshot (which resolves aliases the same way the schema route does).
    """
    fields_by_qualname = {info.qualname: info for info in registered_settings()}
    prefixes: set[str] = set()
    env_vars: set[str] = set()
    for cls in _all_settings_subclasses():
        if cls.__module__.split(".")[0] not in top_levels:
            continue
        prefix = cls.model_config.get("env_prefix", "") or ""
        if prefix:
            prefixes.add(prefix)
            continue
        info = fields_by_qualname.get(f"{cls.__module__}.{cls.__qualname__}")
        if info is not None:
            env_vars |= {field.env_var for field in info.fields if field.env_var}
    return BundledEnvNamespaces(frozenset(prefixes), frozenset(env_vars))
