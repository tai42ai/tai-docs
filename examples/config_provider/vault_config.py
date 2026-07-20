"""A minimal fictional config provider: a ``vault`` mode.

Implements the ``ConfigManager`` ABC — the env surface (``read_env`` /
``write_env``) and the manifest surface (``read_manifest`` /
``read_manifest_preserved`` / ``read_defaults_manifest`` / ``write_manifest`` /
``mutate_manifest`` / ``replace_manifest``) — and exposes a
``build_config_manager()`` factory. The skeleton's config seam loads a provider
by dynamic import of that factory, so there is no static edge in either
direction. This example keeps its backing in memory; a real provider swaps in
its own store (a secrets vault, a database) behind the same eight methods.

``mutate_manifest`` and ``replace_manifest`` are both abstract, so a subclass
that implements only one cannot be instantiated. They are the transactional
write seams feature code uses: each holds exclusive access across the whole
read → modify → write span, so a concurrent writer cannot interleave.
"""

from collections.abc import Callable
from typing import Any

from tai_contract.config import ConfigManager


class VaultConfigManager(ConfigManager):
    def __init__(self) -> None:
        self._env: dict[str, str] = {}
        self._manifest: dict[str, Any] = {}

    def read_env(self) -> dict[str, str]:
        return dict(self._env)

    def write_env(self, config: dict[str, str]) -> None:
        # Merge, preserving keys absent from ``config`` and dropping empty values.
        self._env.update({k: v for k, v in config.items() if v})

    def read_manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    def read_manifest_preserved(self) -> dict[str, Any]:
        # The in-memory backing stores no ``!ENV`` placeholders, so the
        # preserved view equals the resolved one.
        return dict(self._manifest)

    def read_defaults_manifest(self) -> dict[str, Any]:
        return {}

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        self._manifest = dict(manifest)

    def mutate_manifest(self, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        # Read the current document, edit it in place under exclusive access,
        # and persist. The in-memory store serializes writes trivially; a real
        # backend takes a lock or retries on an optimistic-concurrency conflict,
        # so ``mutator`` must be re-runnable.
        document = dict(self._manifest)
        mutator(document)
        self._manifest = document
        return dict(document)

    def replace_manifest(self, document: dict[str, Any]) -> dict[str, Any]:
        # Replace the whole stored document: a key absent from ``document`` is
        # dropped. The caller builds ``document`` from the preserved view so no
        # resolved secret is ever persisted.
        self._manifest = dict(document)
        return dict(self._manifest)


def build_config_manager() -> ConfigManager:
    """Provider entry point for the config mode (the factory convention)."""
    return VaultConfigManager()
