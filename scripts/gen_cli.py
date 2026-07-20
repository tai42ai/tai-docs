#!/usr/bin/env python3
"""Generate the CLI reference (``reference/cli/*.mdx``).

Walks the compiled ``tai`` Typer/click command tree and renders one MDX page per
top-level command group, each with usage, a description, and option/argument
tables for the group and every command beneath it, at any depth. Also rewrites
the CLI group's page list in ``docs.json`` so the nav always matches the files
on disk.

Approach: a hand-rolled click-tree walker (not ``typer utils docs``). The tree
is extracted by running ``scripts/_cli_introspect.py`` inside the tai42-skeleton
environment -- it imports ``tai42_skeleton.cli.app:app`` and dumps the tree as
JSON, so every rendered line traces to the live command objects the runtime
uses for ``--help``. ``typer utils docs`` was rejected: it emits an unstable,
truncated tree here and cannot render leaf commands that carry no help.

Fail-loud contract: if the app cannot be imported, the extraction command exits
non-zero, or the tree is empty, this exits non-zero and writes no pages.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent
SKELETON_DIR = DOCS_ROOT.parent / "tai-skeleton"
INTROSPECT = Path(__file__).resolve().parent / "_cli_introspect.py"
OUTPUT_DIR = DOCS_ROOT / "reference" / "cli"
DOCS_JSON = DOCS_ROOT / "docs.json"
NAV_PREFIX = "reference/cli"


class GenerationError(RuntimeError):
    """A generation step failed; nothing was written."""


# --- extraction -----------------------------------------------------------


def extract_tree() -> dict:
    """Run the introspection helper in the skeleton env and parse its JSON."""
    if not SKELETON_DIR.is_dir():
        raise GenerationError(f"tai42-skeleton checkout not found at {SKELETON_DIR}")
    try:
        proc = subprocess.run(
            ["uv", "run", "python", str(INTROSPECT)],
            cwd=SKELETON_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GenerationError(f"could not launch the introspector: {exc}") from exc
    if proc.returncode != 0:
        raise GenerationError(
            f"the CLI introspector exited {proc.returncode}:\n{proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GenerationError(f"introspector emitted invalid JSON: {exc}") from exc


def validate_tree(tree: object) -> dict:
    """Raise unless the tree is a non-empty command group."""
    if not isinstance(tree, dict):
        raise GenerationError("command tree is not an object")
    commands = tree.get("commands")
    if not isinstance(commands, list) or not commands:
        raise GenerationError("command tree is empty -- no top-level commands found")
    return tree


# --- MDX rendering ---------------------------------------------------------


def _esc(text: str) -> str:
    """Escape MDX-significant characters in prose and table cells."""
    text = (text or "").replace("``", "`")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("{", "&#123;").replace("}", "&#125;")
    return text


def _cell(text: str) -> str:
    """Escape and flatten a value for a single Markdown table cell."""
    return _esc(" ".join((text or "").split())).replace("|", "\\|")


def _frontmatter(title: str, description: str) -> str:
    desc = _esc(" ".join((description or "").split())).replace('"', "'")
    if not desc:
        desc = f"Reference for {title}."
    return f'---\ntitle: "{title}"\ndescription: "{desc}"\nicon: "terminal"\n---\n'


def _usage_line(node: dict) -> str:
    return " ".join(node["path"] + node["usage"])


def _metavar_code(metavar: str) -> str:
    """A metavar as a code span safe inside a Markdown table cell."""
    return f"`{_esc(metavar).replace('|', '\\|')}`"


def _option_label(param: dict) -> str:
    opts = list(param["opts"]) + list(param["secondary_opts"])
    label = " / ".join(f"`{o}`" for o in opts)
    if not param["is_flag"] and param["metavar"]:
        label += f" {_metavar_code(param['metavar'])}"
    return label


def _params_tables(node: dict) -> list[str]:
    out: list[str] = []
    args = [p for p in node["params"] if p["kind"] == "argument"]
    opts = [p for p in node["params"] if p["kind"] == "option"]
    if args:
        out.append("| Argument | Description |")
        out.append("| --- | --- |")
        for p in args:
            desc = p["help"]
            desc += " _(required)_" if p["required"] else " _(optional)_"
            out.append(f"| {_metavar_code(p['metavar'] or p['name'])} | {_cell(desc)} |")
        out.append("")
    if opts:
        out.append("| Option | Description |")
        out.append("| --- | --- |")
        for p in opts:
            desc = p["help"]
            if p["default"] is not None:
                desc += f" _(default: `{p['default']}`)_"
            out.append(f"| {_option_label(p)} | {_cell(desc)} |")
        out.append("")
    return out


def _render_node(node: dict, level: int) -> list[str]:
    """Render one command and, recursively, its subcommands as sections."""
    lines: list[str] = []
    if level > 1:  # top-level heading comes from the page frontmatter
        heading = "#" * min(level, 4)
        lines.append(f"{heading} `{' '.join(node['path'])}`")
        lines.append("")
    if node["help"]:
        for para in node["help"].split("\n\n"):
            lines.append(_esc(para.strip()))
            lines.append("")
    elif level == 1 and node["commands"]:
        lines.append(f"Commands under `{' '.join(node['path'])}`.")
        lines.append("")
    lines.append("```console")
    lines.append(f"$ {_usage_line(node)}")
    lines.append("```")
    lines.append("")
    lines.extend(_params_tables(node))
    for sub in node["commands"]:
        lines.extend(_render_node(sub, level + 1))
    return lines


def render_page(node: dict) -> str:
    title = " ".join(node["path"])
    description = node["short_help"] or node["help"].split("\n")[0]
    body = "\n".join(_render_node(node, level=1)).rstrip() + "\n"
    return _frontmatter(title, description) + "\n" + body


# --- docs.json nav ---------------------------------------------------------


def update_nav(page_slugs: list[str]) -> None:
    """Rewrite the Reference -> CLI group's pages to match the generated files."""
    docs = json.loads(DOCS_JSON.read_text(encoding="utf-8"))
    pages = [f"{NAV_PREFIX}/index"] + [f"{NAV_PREFIX}/{slug}" for slug in page_slugs]
    for tab in docs["navigation"]["tabs"]:
        if tab.get("tab") != "Reference":
            continue
        for group in tab["groups"]:
            if group.get("group") == "CLI":
                group["pages"] = pages
                DOCS_JSON.write_text(
                    json.dumps(docs, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                return
    raise GenerationError("could not find the Reference -> CLI group in docs.json")


# --- driver ----------------------------------------------------------------


def generate() -> list[str]:
    tree = validate_tree(extract_tree())
    # Render every page into memory FIRST, so a malformed node raises before the
    # output directory is touched -- a bad tree leaves the committed reference
    # intact rather than a half-written one.
    rendered: dict[str, str] = {}
    for node in tree["commands"]:
        rendered[node["name"]] = render_page(node)
    slugs = list(rendered)

    # All pages rendered cleanly -- safe to clear stale pages and write.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for existing in OUTPUT_DIR.glob("*.mdx"):
        if existing.name != "index.mdx":  # keep the hand-written index
            existing.unlink()
    for slug, text in rendered.items():
        (OUTPUT_DIR / f"{slug}.mdx").write_text(text, encoding="utf-8")
    update_nav(slugs)
    return slugs


def main() -> int:
    try:
        slugs = generate()
    except GenerationError as exc:
        print(f"gen_cli: FAILED -- {exc}", file=sys.stderr)
        print("gen_cli: no pages written", file=sys.stderr)
        return 1
    print(
        f"gen_cli: wrote {len(slugs)} command pages under "
        f"{OUTPUT_DIR.relative_to(DOCS_ROOT)}/ and updated docs.json nav"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
