#!/usr/bin/env python3
"""Assert a bijection between one screenshot set's staged shots and the page embeds that show them.

A capture sweep writes its shots into a staging dir (``SHOTS_OUT``), one dir per stack
state the sweep runs on; the staged set is their union. The docs pages under a pages root
embed those images as ``<embed prefix><filename>`` (for example ``/images/studio/``). This
check reads both sides and requires them to be exactly equal, in both directions:

* every image a page embeds under the prefix is present in a staging dir -- otherwise a
  page shows a shot the sweep never produced;
* every staged shot is embedded by some page -- otherwise a shot is dead weight that no
  page displays.

A themed set (one ``--theme`` per colour scheme) names each shot ``<key>-<theme>.png``
and needs every key in every theme; a set with no ``--theme`` names each shot
``<key>.png``. Either mismatch -- or a key missing a theme, a shot staged in more than one
dir, or a filename that is not a ``.png`` of the set's naming -- fails loudly, naming the
offending file and the page it came from, so a broken or partial set is never copied into
the docs.

Usage::

    check_shot_parity.py --shots-dir <staging dir> [--shots-dir <staging dir> ...]
        --pages-root <docs dir> --embed-prefix <served path prefix> [--theme <name> ...]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")


@dataclass(frozen=True)
class ShotSet:
    """One screenshot set: the path prefix its images are served under and its themes.

    ``themes`` is empty for a set captured in a single, unthemed rendering.
    """

    embed_prefix: str
    themes: tuple[str, ...] = ()

    def embed_pattern(self) -> re.Pattern[str]:
        """The pattern of an embed of this set's images, capturing the bare filename."""
        return re.compile(re.escape(self.embed_prefix) + r"([A-Za-z0-9._-]+\.png)")

    def naming(self) -> str:
        """The set's filename shape, as the error messages state it."""
        if not self.themes:
            return "expected <key>.png"
        return "expected " + " / ".join(f"<key>-{theme}.png" for theme in self.themes)

    def split(self, filename: str) -> tuple[str, str] | None:
        """Return ``(key, theme)`` for a well-formed filename of this set, or ``None``.

        An unthemed set's theme is the empty string.
        """
        if not self.themes:
            match = re.match(r"^(?P<key>[A-Za-z0-9._-]+)\.png$", filename)
            return None if match is None else (match.group("key"), "")
        themes = "|".join(re.escape(theme) for theme in self.themes)
        match = re.match(rf"^(?P<key>.+)-(?P<theme>{themes})\.png$", filename)
        return None if match is None else (match.group("key"), match.group("theme"))


def _blank(match: re.Match[str]) -> str:
    """Replace a matched span with same-length whitespace, keeping newlines intact."""
    return re.sub(r"[^\n]", " ", match.group(0))


def find_embedded_shots(pages_root: Path, shot_set: ShotSet) -> dict[str, list[str]]:
    """Map each embedded ``<name>.png`` of ``shot_set`` to the ``page:line`` locations that embed it.

    Code spans (fenced blocks and inline code) are blanked first so a path shown as a
    documentation example is never mistaken for a live embed.
    """
    pattern = shot_set.embed_pattern()
    embedded: dict[str, list[str]] = {}
    for mdx in sorted(pages_root.rglob("*.mdx")):
        rel = mdx.relative_to(pages_root.parent)
        text = mdx.read_text(encoding="utf-8")
        blanked = _INLINE_CODE.sub(_blank, _FENCED_CODE.sub(_blank, text))
        for match in pattern.finditer(blanked):
            filename = match.group(1)
            lineno = blanked.count("\n", 0, match.start()) + 1
            embedded.setdefault(filename, []).append(f"{rel}:{lineno}")
    return embedded


def find_staged_shots(*shots_dirs: Path) -> dict[str, list[str]]:
    """Map each file staged in any of ``shots_dirs`` (bare filename) to the dirs holding it."""
    staged: dict[str, list[str]] = {}
    for shots_dir in shots_dirs:
        for p in sorted(shots_dir.iterdir()):
            if p.is_file():
                staged.setdefault(p.name, []).append(str(shots_dir))
    return staged


def _themes_by_key(filenames: set[str], shot_set: ShotSet) -> dict[str, set[str]]:
    """Group well-formed filenames of ``shot_set`` into ``key -> {themes}``."""
    keyed: dict[str, set[str]] = {}
    for filename in filenames:
        parts = shot_set.split(filename)
        if parts is not None:
            key, theme = parts
            keyed.setdefault(key, set()).add(theme)
    return keyed


def check_parity(embedded: dict[str, list[str]], staged: dict[str, list[str]], shot_set: ShotSet) -> list[str]:
    """Return every parity violation between embedded and staged shots (empty when equal)."""
    prefix = shot_set.embed_prefix
    naming = shot_set.naming()
    errors: list[str] = [
        f"{', '.join(embedded[fn])}: page embeds {prefix}{fn}, which is not a shot of this set ({naming})"
        for fn in sorted(embedded)
        if shot_set.split(fn) is None
    ]
    errors.extend(
        f"staged shot {fn!r} is not a shot of this set ({naming})"
        for fn in sorted(staged)
        if shot_set.split(fn) is None
    )
    errors.extend(
        f"staged twice: {fn} is in {' and '.join(staged[fn])}; each shot belongs to one stack state"
        for fn in sorted(staged)
        if len(staged[fn]) > 1
    )

    embedded_files = {f for f in embedded if shot_set.split(f) is not None}
    staged_files = {f for f in staged if shot_set.split(f) is not None}

    if shot_set.themes:
        for label, keyed in (
            ("the pages have", _themes_by_key(embedded_files, shot_set)),
            ("the sweep has", _themes_by_key(staged_files, shot_set)),
        ):
            errors.extend(
                f"{label} {key}-{sorted(keyed[key])[0]}.png but not {key}-{theme}.png; "
                "a shot of this set needs every theme"
                for key in sorted(keyed)
                for theme in sorted(set(shot_set.themes) - keyed[key])
            )

    errors.extend(
        f"{', '.join(embedded[fn])}: page embeds {prefix}{fn} but the sweep staged no {fn}"
        for fn in sorted(embedded_files - staged_files)
    )
    errors.extend(
        f"the sweep staged {fn} but no page embeds {prefix}{fn} (dead shot)"
        for fn in sorted(staged_files - embedded_files)
    )
    return errors


def main(argv: list[str] | None = None) -> int:
    """Check parity and report; return 1 on any violation, else 0."""
    parser = argparse.ArgumentParser(description="Check one screenshot set's parity with its page embeds before copy.")
    parser.add_argument(
        "--shots-dir",
        type=Path,
        action="append",
        required=True,
        help="staging dir of the set's shots; repeat it for each stack state's dir",
    )
    parser.add_argument(
        "--pages-root",
        type=Path,
        required=True,
        help="docs tree whose embeds define the set",
    )
    parser.add_argument(
        "--embed-prefix",
        required=True,
        help="served path prefix of the set's images, e.g. /images/studio/",
    )
    parser.add_argument(
        "--theme",
        action="append",
        default=[],
        help="a colour scheme every shot is captured in (<key>-<theme>.png); repeat per theme, omit for <key>.png",
    )
    args = parser.parse_args(argv)
    shot_set = ShotSet(embed_prefix=args.embed_prefix, themes=tuple(args.theme))

    missing = [d for d in args.shots_dir if not d.is_dir()]
    if missing:
        for shots_dir in missing:
            print(f"check_shot_parity: staging dir does not exist: {shots_dir}", file=sys.stderr)
        return 1
    if not args.pages_root.is_dir():
        print(f"check_shot_parity: docs tree does not exist: {args.pages_root}", file=sys.stderr)
        return 1

    embedded = find_embedded_shots(args.pages_root, shot_set)
    staged = find_staged_shots(*args.shots_dir)
    errors = check_parity(embedded, staged, shot_set)

    if errors:
        print(f"check_shot_parity: {len(errors)} screenshot parity violation(s):", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(
        f"check_shot_parity: {len(staged)} staged shot(s) in bijection with the {shot_set.embed_prefix} embeds "
        f"under {args.pages_root}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
