"""The generator's error type."""

from __future__ import annotations


class GenerationError(RuntimeError):
    """Raised when the reference cannot be generated (fail-loud)."""
