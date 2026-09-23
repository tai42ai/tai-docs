#!/usr/bin/env python3
"""Assert a bijection between the staged flow-editor screenshots and their page embeds.

The editor screenshot sweep writes ``<key>-light.png`` / ``<key>-dark.png`` pairs
into a staging dir (``SHOTS_OUT``). The flow-author pages under ``babelfish/`` embed
those images as ``/images/studio/<key>-<theme>.png``. This check reads both sides and
requires them to be exactly equal, in both directions:

* every image a flow-author page embeds is present in the staging dir -- otherwise a
  page shows a shot the sweep never produced;
* every staged shot is embedded by some flow-author page -- otherwise a shot is dead
  weight that no page displays.

Either mismatch -- or a shot present in only one theme, or a filename that is not a
themed ``<key>-<theme>.png`` pair -- fails loudly, naming the offending file and the
page it came from, so a broken or partial set is never copied into the docs.

Usage::

    check_editor_shots.py --shots-dir <staging dir> [--pages-root <flow-author docs dir>]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

# The flow-author page tree whose embeds define the editor screenshot set. Every
# ``/images/studio/*.png`` these pages embed is an editor shot; the Studio screens
# are embedded by other page trees, so the two filename sets never overlap.
DEFAULT_PAGES_ROOT = REPO_ROOT / "babelfish"

# The path prefix under which every screenshot is served in the docs.
EMBED_PREFIX = "/images/studio/"

# The two colour schemes every editor shot captures; a key needs both.
THEMES = ("light", "dark")

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_EMBED = re.compile(re.escape(EMBED_PREFIX) + r"([A-Za-z0-9._-]+\.png)")
_SHOT = re.compile(r"^(?P<key>.+)-(?P<theme>light|dark)\.png$")


def split_shot(filename: str) -> tuple[str, str] | None:
    """Return ``(key, theme)`` for a ``<key>-<theme>.png`` name, or ``None`` when malformed."""
    match = _SHOT.match(filename)
    if match is None:
        return None
    return match.group("key"), match.group("theme")


def _blank(match: re.Match[str]) -> str:
    """Replace a matched span with same-length whitespace, keeping newlines intact."""
    return re.sub(r"[^\n]", " ", match.group(0))


def find_embedded_shots(pages_root: Path) -> dict[str, list[str]]:
    """Map each embedded ``<name>.png`` to the ``page:line`` locations that embed it.

    Code spans (fenced blocks and inline code) are blanked first so a path shown as a
    documentation example is never mistaken for a live embed.
    """
    embedded: dict[str, list[str]] = {}
    for mdx in sorted(pages_root.rglob("*.mdx")):
        rel = mdx.relative_to(pages_root.parent)
        text = mdx.read_text(encoding="utf-8")
        blanked = _INLINE_CODE.sub(_blank, _FENCED_CODE.sub(_blank, text))
        for match in _EMBED.finditer(blanked):
            filename = match.group(1)
            lineno = blanked.count("\n", 0, match.start()) + 1
            embedded.setdefault(filename, []).append(f"{rel}:{lineno}")
    return embedded


def find_staged_shots(shots_dir: Path) -> list[str]:
    """Return every file staged in ``shots_dir`` as bare filenames, sorted."""
    return sorted(p.name for p in shots_dir.iterdir() if p.is_file())


def _themes_by_key(filenames: set[str]) -> dict[str, set[str]]:
    """Group well-formed ``<key>-<theme>.png`` filenames into ``key -> {themes}``."""
    keyed: dict[str, set[str]] = {}
    for filename in filenames:
        parts = split_shot(filename)
        if parts is not None:
            key, theme = parts
            keyed.setdefault(key, set()).add(theme)
    return keyed


def check_parity(embedded: dict[str, list[str]], staged: list[str]) -> list[str]:
    """Return every parity violation between embedded and staged shots (empty when equal)."""
    malformed_hint = "expected <key>-light.png / <key>-dark.png"
    errors: list[str] = [
        f"{', '.join(embedded[fn])}: flow-author page embeds {EMBED_PREFIX}{fn}, "
        f"which is not a themed editor shot ({malformed_hint})"
        for fn in sorted(embedded)
        if split_shot(fn) is None
    ]
    errors.extend(
        f"staged shot {fn!r} is not a themed editor shot ({malformed_hint})" for fn in staged if split_shot(fn) is None
    )

    embedded_files = {f for f in embedded if split_shot(f) is not None}
    staged_files = {f for f in staged if split_shot(f) is not None}

    for label, keyed in (
        ("flow-author page", _themes_by_key(embedded_files)),
        ("editor sweep", _themes_by_key(staged_files)),
    ):
        errors.extend(
            f"{label} has {key}-{sorted(keyed[key])[0]}.png but not {key}-{theme}.png; an editor shot needs both themes"
            for key in sorted(keyed)
            for theme in sorted(set(THEMES) - keyed[key])
        )

    errors.extend(
        f"{', '.join(embedded[fn])}: flow-author page embeds {EMBED_PREFIX}{fn} but the editor sweep staged no {fn}"
        for fn in sorted(embedded_files - staged_files)
    )
    errors.extend(
        f"the editor sweep staged {fn} but no flow-author page embeds {EMBED_PREFIX}{fn} (dead shot)"
        for fn in sorted(staged_files - embedded_files)
    )
    return errors


def main(argv: list[str] | None = None) -> int:
    """Check parity and report; return 1 on any violation, else 0."""
    parser = argparse.ArgumentParser(description="Check editor-screenshot parity before copy.")
    parser.add_argument("--shots-dir", type=Path, required=True, help="staging dir of <key>-<theme>.png shots")
    parser.add_argument(
        "--pages-root",
        type=Path,
        default=DEFAULT_PAGES_ROOT,
        help="flow-author docs tree whose embeds define the editor set",
    )
    args = parser.parse_args(argv)

    if not args.shots_dir.is_dir():
        print(f"check_editor_shots: staging dir does not exist: {args.shots_dir}", file=sys.stderr)
        return 1
    if not args.pages_root.is_dir():
        print(f"check_editor_shots: flow-author docs tree does not exist: {args.pages_root}", file=sys.stderr)
        return 1

    embedded = find_embedded_shots(args.pages_root)
    staged = find_staged_shots(args.shots_dir)
    errors = check_parity(embedded, staged)

    if errors:
        print(f"check_editor_shots: {len(errors)} editor-screenshot parity violation(s):", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"check_editor_shots: {len(staged)} staged shot(s) in bijection with the flow-author embeds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
