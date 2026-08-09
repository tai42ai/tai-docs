#!/usr/bin/env python3
"""Adapter onto the kit's canonical ``validate_docs``.

The docs-site generator is the third enforcement point of the ONE docs contract
(marketplace ingest and the monorepo CI gate are the other two). It re-runs the
same ``tai42_kit.plugins.validate_docs`` on every fetched payload rather than
hand-rolling a subset check, so the three points can never diverge.
"""

from __future__ import annotations


class DocsValidationError(RuntimeError):
    """A fetched docs payload violated the canonical contract."""


def validate_docs_payload(files: dict[str, bytes], *, first_party: bool) -> None:
    """Validate ``{docs-relative-path: bytes}`` via the kit; raise loudly on any
    violation. ``first_party`` relaxes the third-party mdx safe-subset only."""
    try:
        from tai42_kit.plugins import PluginDocsError, validate_docs
    except ImportError as exc:  # pragma: no cover - environment guard
        raise DocsValidationError(
            f"tai42_kit is not importable ({exc}); run gen_plugins where the kit resolves"
        ) from exc
    try:
        validate_docs(files, first_party=first_party)
    except PluginDocsError as exc:
        raise DocsValidationError(str(exc)) from exc
