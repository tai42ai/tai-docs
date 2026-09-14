"""Phase modules for the Studio SDK reference generator.

The generator entry point (``scripts/gen_studio_sdk.py``) composes these modules;
each owns one phase — static configuration, the error type, acquiring and indexing
the TypeDoc model, rendering a type node to a string, rendering a symbol to MDX,
assembling pages, and wiring the docs.json nav. Consumers import the submodules
directly; this package exposes no re-export surface.
"""
