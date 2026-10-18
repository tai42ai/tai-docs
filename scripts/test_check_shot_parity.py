#!/usr/bin/env python3
"""Tests for the screenshot-set parity check (standard-library only)::

uv run pytest scripts/test_check_shot_parity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_shot_parity  # noqa: E402
from check_shot_parity import ShotSet  # noqa: E402

KEYS = ("holder-panel", "ask-exit", "warm-start")
THEMED = ShotSet(embed_prefix="/images/studio/", themes=("light", "dark"))
UNTHEMED = ShotSet(embed_prefix="/images/page/")
THEMED_ARGS = ["--embed-prefix", "/images/studio/", "--theme", "light", "--theme", "dark"]


def _embed_line(key: str, theme: str) -> str:
    return f'  <img src="/images/studio/{key}-{theme}.png" alt="{key}" />\n'


def _write_page(pages_root: Path, name: str, keys: tuple[str, ...]) -> Path:
    pages_root.mkdir(parents=True, exist_ok=True)
    body = "# page\n\n" + "".join(_embed_line(k, t) for k in keys for t in ("light", "dark"))
    page = pages_root / name
    page.write_text(body, encoding="utf-8")
    return page


def _stage(shots_dir: Path, keys: tuple[str, ...]) -> Path:
    shots_dir.mkdir(parents=True, exist_ok=True)
    for key in keys:
        for theme in ("light", "dark"):
            (shots_dir / f"{key}-{theme}.png").write_bytes(b"png")
    return shots_dir


def _parity(pages: Path, shot_set: ShotSet, *shots_dirs: Path) -> list[str]:
    embedded = check_shot_parity.find_embedded_shots(pages, shot_set)
    return check_shot_parity.check_parity(embedded, check_shot_parity.find_staged_shots(*shots_dirs), shot_set)


def test_split_themed() -> None:
    assert THEMED.split("holder-panel-light.png") == ("holder-panel", "light")
    assert THEMED.split("run-panel-ask-dark.png") == ("run-panel-ask", "dark")
    assert THEMED.split("holder-panel.png") is None
    assert THEMED.split("holder-panel-sepia.png") is None


def test_split_unthemed() -> None:
    assert UNTHEMED.split("form-field-error.png") == ("form-field-error", "")
    assert UNTHEMED.split("form-field-error.jpg") is None


def test_equal_sets_pass(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    shots = _stage(tmp_path / "shots", KEYS)
    assert _parity(pages, THEMED, shots) == []


def test_union_of_staging_dirs_passes(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    default = _stage(tmp_path / "default", ("holder-panel", "ask-exit"))
    monitoring = _stage(tmp_path / "monitoring", ("warm-start",))
    assert _parity(pages, THEMED, default, monitoring) == []


def test_shot_staged_in_two_dirs_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    default = _stage(tmp_path / "default", KEYS)
    monitoring = _stage(tmp_path / "monitoring", ("warm-start",))
    errors = _parity(pages, THEMED, default, monitoring)
    duplicates = [e for e in errors if "staged twice" in e]
    assert len(duplicates) == 2, errors
    assert all("warm-start" in e and str(default) in e and str(monitoring) in e for e in duplicates)


def test_embedded_not_staged_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    shots = _stage(tmp_path / "shots", ("holder-panel", "ask-exit"))  # warm-start absent
    joined = "\n".join(_parity(pages, THEMED, shots))
    assert "warm-start-light.png" in joined
    assert "warm-start-dark.png" in joined
    assert "index.mdx" in joined
    assert "staged no" in joined


def test_staged_not_embedded_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", ("holder-panel", "ask-exit"))
    shots = _stage(tmp_path / "shots", KEYS)  # warm-start staged but not embedded
    joined = "\n".join(_parity(pages, THEMED, shots))
    assert "warm-start-light.png" in joined
    assert "dead shot" in joined


def test_partial_staged_pair_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", ("holder-panel",))
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "holder-panel-light.png").write_bytes(b"png")  # dark missing
    joined = "\n".join(_parity(pages, THEMED, shots))
    assert "the sweep has holder-panel-light.png but not holder-panel-dark.png" in joined
    assert "every theme" in joined


def test_partial_embedded_pair_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "index.mdx").write_text(_embed_line("holder-panel", "light"), encoding="utf-8")
    shots = _stage(tmp_path / "shots", ("holder-panel",))
    joined = "\n".join(_parity(pages, THEMED, shots))
    assert "the pages have holder-panel-light.png but not holder-panel-dark.png" in joined
    assert "every theme" in joined


def test_malformed_embed_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "index.mdx").write_text('<img src="/images/studio/holder-panel.png" alt="x" />\n', encoding="utf-8")
    shots = tmp_path / "shots"
    shots.mkdir()
    joined = "\n".join(_parity(pages, THEMED, shots))
    assert "not a shot of this set" in joined
    assert "<key>-light.png / <key>-dark.png" in joined
    assert "index.mdx:1" in joined


def test_malformed_staged_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", ())
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "stray.png").write_bytes(b"png")
    errors = _parity(pages, THEMED, shots)
    assert any("not a shot of this set" in e and "stray.png" in e for e in errors)


def test_other_prefix_embeds_are_not_this_set(tmp_path: Path) -> None:
    pages = tmp_path / "docs"
    pages.mkdir(parents=True)
    (pages / "index.mdx").write_text(
        '<img src="/images/studio/holder-panel-light.png" />\n<img src="/images/page/form-field-error.png" />\n',
        encoding="utf-8",
    )
    assert set(check_shot_parity.find_embedded_shots(pages, UNTHEMED)) == {"form-field-error.png"}


def test_unthemed_equal_sets_pass(tmp_path: Path) -> None:
    pages = tmp_path / "docs"
    (pages / "concepts").mkdir(parents=True)
    (pages / "concepts" / "page.mdx").write_text('<img src="/images/page/form-field-error.png" />\n', encoding="utf-8")
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "form-field-error.png").write_bytes(b"png")
    assert _parity(pages, UNTHEMED, shots) == []


def test_unthemed_mismatch_fails(tmp_path: Path) -> None:
    pages = tmp_path / "docs"
    pages.mkdir(parents=True)
    (pages / "page.mdx").write_text('<img src="/images/page/form-field-error.png" />\n', encoding="utf-8")
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "other.png").write_bytes(b"png")
    (shots / "notes.txt").write_bytes(b"x")
    joined = "\n".join(_parity(pages, UNTHEMED, shots))
    assert "staged no form-field-error.png" in joined
    assert "the sweep staged other.png but no page embeds /images/page/other.png (dead shot)" in joined
    assert "'notes.txt' is not a shot of this set (expected <key>.png)" in joined


def test_embed_in_code_fence_ignored(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "index.mdx").write_text(
        "# doc\n\n```\n/images/studio/example-light.png\n```\n"
        '<img src="/images/studio/holder-panel-light.png" />\n'
        '<img src="/images/studio/holder-panel-dark.png" />\n',
        encoding="utf-8",
    )
    embedded = check_shot_parity.find_embedded_shots(pages, THEMED)
    assert set(embedded) == {"holder-panel-light.png", "holder-panel-dark.png"}


def test_inline_code_embed_ignored(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "index.mdx").write_text("Reference `/images/studio/inline-light.png` in prose.\n", encoding="utf-8")
    assert check_shot_parity.find_embedded_shots(pages, THEMED) == {}


def test_line_numbers_are_accurate(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "studio.mdx").write_text(
        '# heading\n\nsome prose\n<img src="/images/studio/holder-panel-light.png" />\n',
        encoding="utf-8",
    )
    embedded = check_shot_parity.find_embedded_shots(pages, THEMED)
    assert embedded["holder-panel-light.png"] == ["babelfish/studio.mdx:4"]


def test_main_passes_on_equal_sets(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    shots = _stage(tmp_path / "shots", KEYS)
    rc = check_shot_parity.main(["--shots-dir", str(shots), "--pages-root", str(pages), *THEMED_ARGS])
    assert rc == 0


def test_main_accepts_repeated_shots_dir(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    default = _stage(tmp_path / "default", ("holder-panel", "ask-exit"))
    monitoring = _stage(tmp_path / "monitoring", ("warm-start",))
    argv = ["--shots-dir", str(default), "--shots-dir", str(monitoring), "--pages-root", str(pages), *THEMED_ARGS]
    assert check_shot_parity.main(argv) == 0


def test_main_unthemed_set(tmp_path: Path) -> None:
    pages = tmp_path / "docs"
    pages.mkdir(parents=True)
    (pages / "page.mdx").write_text('<img src="/images/page/form-field-error.png" />\n', encoding="utf-8")
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "form-field-error.png").write_bytes(b"png")
    argv = ["--shots-dir", str(shots), "--pages-root", str(pages), "--embed-prefix", "/images/page/"]
    assert check_shot_parity.main(argv) == 0


def test_main_fails_on_mismatch(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    shots = _stage(tmp_path / "shots", ("holder-panel",))
    rc = check_shot_parity.main(["--shots-dir", str(shots), "--pages-root", str(pages), *THEMED_ARGS])
    assert rc == 1


def test_main_fails_on_missing_shots_dir(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", ())
    argv = ["--shots-dir", str(tmp_path / "nope"), "--pages-root", str(pages), *THEMED_ARGS]
    assert check_shot_parity.main(argv) == 1


def test_main_fails_on_missing_pages_root(tmp_path: Path) -> None:
    shots = _stage(tmp_path / "shots", ())
    argv = ["--shots-dir", str(shots), "--pages-root", str(tmp_path / "nope"), *THEMED_ARGS]
    assert check_shot_parity.main(argv) == 1
