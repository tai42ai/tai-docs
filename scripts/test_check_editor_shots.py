#!/usr/bin/env python3
"""Tests for the editor-screenshot parity check (standard-library only)::

uv run pytest scripts/test_check_editor_shots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import check_editor_shots  # noqa: E402

KEYS = ("holder-panel", "ask-exit", "warm-start")


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


def test_split_shot() -> None:
    assert check_editor_shots.split_shot("holder-panel-light.png") == ("holder-panel", "light")
    assert check_editor_shots.split_shot("run-panel-ask-dark.png") == ("run-panel-ask", "dark")
    assert check_editor_shots.split_shot("holder-panel.png") is None
    assert check_editor_shots.split_shot("holder-panel-sepia.png") is None


def test_equal_sets_pass(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    shots = _stage(tmp_path / "shots", KEYS)
    embedded = check_editor_shots.find_embedded_shots(pages)
    staged = check_editor_shots.find_staged_shots(shots)
    assert check_editor_shots.check_parity(embedded, staged) == []


def test_embedded_not_staged_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    shots = _stage(tmp_path / "shots", ("holder-panel", "ask-exit"))  # warm-start absent
    embedded = check_editor_shots.find_embedded_shots(pages)
    errors = check_editor_shots.check_parity(embedded, check_editor_shots.find_staged_shots(shots))
    joined = "\n".join(errors)
    assert "warm-start-light.png" in joined
    assert "warm-start-dark.png" in joined
    assert "index.mdx" in joined
    assert "staged no" in joined


def test_staged_not_embedded_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", ("holder-panel", "ask-exit"))
    shots = _stage(tmp_path / "shots", KEYS)  # warm-start staged but not embedded
    embedded = check_editor_shots.find_embedded_shots(pages)
    errors = check_editor_shots.check_parity(embedded, check_editor_shots.find_staged_shots(shots))
    joined = "\n".join(errors)
    assert "warm-start-light.png" in joined
    assert "dead shot" in joined


def test_partial_staged_pair_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", ("holder-panel",))
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "holder-panel-light.png").write_bytes(b"png")  # dark missing
    embedded = check_editor_shots.find_embedded_shots(pages)
    errors = check_editor_shots.check_parity(embedded, check_editor_shots.find_staged_shots(shots))
    joined = "\n".join(errors)
    assert "holder-panel-dark.png" in joined
    assert "both themes" in joined


def test_partial_embedded_pair_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "index.mdx").write_text(_embed_line("holder-panel", "light"), encoding="utf-8")
    shots = _stage(tmp_path / "shots", ("holder-panel",))
    embedded = check_editor_shots.find_embedded_shots(pages)
    errors = check_editor_shots.check_parity(embedded, check_editor_shots.find_staged_shots(shots))
    joined = "\n".join(errors)
    assert "holder-panel-dark.png" in joined
    assert "both themes" in joined


def test_malformed_embed_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "index.mdx").write_text('<img src="/images/studio/holder-panel.png" alt="x" />\n', encoding="utf-8")
    shots = tmp_path / "shots"
    shots.mkdir()
    embedded = check_editor_shots.find_embedded_shots(pages)
    errors = check_editor_shots.check_parity(embedded, check_editor_shots.find_staged_shots(shots))
    joined = "\n".join(errors)
    assert "not a themed editor shot" in joined
    assert "index.mdx:1" in joined


def test_malformed_staged_fails(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", ())
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "stray.png").write_bytes(b"png")
    embedded = check_editor_shots.find_embedded_shots(pages)
    errors = check_editor_shots.check_parity(embedded, check_editor_shots.find_staged_shots(shots))
    assert any("not a themed editor shot" in e and "stray.png" in e for e in errors)


def test_embed_in_code_fence_ignored(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "index.mdx").write_text(
        "# doc\n\n```\n/images/studio/example-light.png\n```\n"
        '<img src="/images/studio/holder-panel-light.png" />\n'
        '<img src="/images/studio/holder-panel-dark.png" />\n',
        encoding="utf-8",
    )
    embedded = check_editor_shots.find_embedded_shots(pages)
    assert set(embedded) == {"holder-panel-light.png", "holder-panel-dark.png"}


def test_inline_code_embed_ignored(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "index.mdx").write_text("Reference `/images/studio/inline-light.png` in prose.\n", encoding="utf-8")
    assert check_editor_shots.find_embedded_shots(pages) == {}


def test_line_numbers_are_accurate(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    pages.mkdir(parents=True)
    (pages / "studio.mdx").write_text(
        '# heading\n\nsome prose\n<img src="/images/studio/holder-panel-light.png" />\n',
        encoding="utf-8",
    )
    embedded = check_editor_shots.find_embedded_shots(pages)
    assert embedded["holder-panel-light.png"] == ["babelfish/studio.mdx:4"]


def test_main_passes_on_equal_sets(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    shots = _stage(tmp_path / "shots", KEYS)
    rc = check_editor_shots.main(["--shots-dir", str(shots), "--pages-root", str(pages)])
    assert rc == 0


def test_main_fails_on_mismatch(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", KEYS)
    shots = _stage(tmp_path / "shots", ("holder-panel",))
    rc = check_editor_shots.main(["--shots-dir", str(shots), "--pages-root", str(pages)])
    assert rc == 1


def test_main_fails_on_missing_shots_dir(tmp_path: Path) -> None:
    pages = tmp_path / "babelfish"
    _write_page(pages, "index.mdx", ())
    rc = check_editor_shots.main(["--shots-dir", str(tmp_path / "nope"), "--pages-root", str(pages)])
    assert rc == 1
