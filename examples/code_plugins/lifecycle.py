"""A minimal fictional lifecycle plugin.

Register a handler with ``@tai_app.lifecycle.on_startup``, ``on_shutdown``, or
``on_reload`` to run code at process startup, shutdown, or after an in-place
reload. An ``on_reload`` handler re-runs after every reload — use it for dynamic
loaders that ``on_startup`` ran once. Load the module under ``lifecycle_modules``.
"""

from tai_contract.app import tai_app

_warm: dict[str, str] = {}


@tai_app.lifecycle.on_startup
def warm_caches() -> None:
    _warm["region_index"] = "loaded"


@tai_app.lifecycle.on_reload
def reload_caches() -> None:
    _warm["region_index"] = "reloaded"
