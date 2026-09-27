"""MDX text helpers for the Python SDK reference generator.

These turn docstring prose and signature values into MDX that the docs site
renders safely: escaping the characters the MDX parser treats as JSX, leaving
fenced blocks and inline code verbatim, folding RST setext headings to bold, and
formatting Markdown table cells. ``gen_sdk`` imports them; keeping them here
keeps that module focused on the griffe object model.
"""

from __future__ import annotations

import re

# RST cross-reference roles (``:class:`Foo```) that appear in docstrings; strip
# the role prefix so the backtick span renders as plain inline code.
_RST_ROLE = re.compile(r":(?:class|mod|func|meth|obj|attr|data|exc|ref|term):(`)")
# Sphinx ``~pkg.mod.Name`` shorthand inside a code span -> just ``Name``.
_RST_TILDE = re.compile(r"`~([A-Za-z0-9_.]+)`")
_CODE_SPAN = re.compile(r"``[^`]*``|`[^`]*`")
# Fenced code block (```lang ... ```). Its body must pass through verbatim:
# escaping it would corrupt code such as ``dict[str, Any]`` displays or
# comparison operators inside a docstring example.
_CODE_FENCE = re.compile(r"^```.*?^```[ \t]*$", re.DOTALL | re.MULTILINE)

# Shortest run of underline characters an RST setext heading uses.
_SETEXT_MIN = 3


def _tilde_last(match: re.Match) -> str:
    return "`" + match.group(1).rsplit(".", 1)[-1] + "`"


def _is_setext_underline(line: str) -> bool:
    """True for a line of only ``-`` or only ``=`` (length >= 3), a setext rule."""
    stripped = line.rstrip()
    return len(stripped) >= _SETEXT_MIN and (set(stripped) == {"-"} or set(stripped) == {"="})


def _rst_setext_to_bold(text: str) -> str:
    """Turn an RST setext heading into a bold run-in paragraph.

    A non-blank text line immediately followed by a line of only ``-`` or ``=``
    is an RST section title; it becomes ``**Title**`` on its own paragraph and
    the underline line is dropped, so it renders as emphasised text rather than
    a Markdown setext heading that would enter the page's on-page table of
    contents beside the SDK symbols. A dash/equals line that follows a blank
    line is a thematic break, not a heading — the non-blank-title test leaves it
    untouched. Callers pass fence-free, table-free prose; fenced blocks are
    split out before this runs, and a table's rule row carries pipes so it is
    never all-dashes.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < n else ""
        if line.strip() and _is_setext_underline(nxt):
            if out and out[-1].strip():
                out.append("")
            out.append(f"**{line.strip()}**")
            out.append("")
            i += 2
            # A blank line already following the underline would double the one
            # just added; skip it so exactly one blank separates the heading.
            if i < n and not lines[i].strip():
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def mdx_escape_prose(text: str) -> str:
    """Escape MDX-hostile characters in prose while leaving code untouched.

    Fenced blocks (```...```) and inline-code spans (single- or double-backtick)
    pass through verbatim, so fenced examples and annotations like
    ``dict[str, Any]`` survive while stray ``{`` / ``<`` in narrative cannot
    break the MDX parser. Each fence-free stretch first has RST setext headings
    folded to bold paragraphs (``_rst_setext_to_bold``) so a docstring section
    title does not become an on-page-TOC heading.
    """
    out: list[str] = []
    last = 0
    for fence in _CODE_FENCE.finditer(text):
        out.append(_escape_prose_segment(_rst_setext_to_bold(text[last : fence.start()])))
        out.append(fence.group(0))  # fenced block: leave verbatim
        last = fence.end()
    out.append(_escape_prose_segment(_rst_setext_to_bold(text[last:])))
    return "".join(out)


def _escape_prose_segment(text: str) -> str:
    """Escape one fence-free stretch, leaving inline-code spans verbatim."""
    text = _RST_ROLE.sub(r"\1", text)
    text = _RST_TILDE.sub(_tilde_last, text)

    out: list[str] = []
    last = 0
    for match in _CODE_SPAN.finditer(text):
        out.append(_escape_segment(text[last : match.start()]))
        out.append(match.group(0))  # code span: leave verbatim
        last = match.end()
    out.append(_escape_segment(text[last:]))
    return "".join(out)


def _escape_segment(seg: str) -> str:
    return seg.replace("{", "&#123;").replace("}", "&#125;").replace("<", "&lt;").replace(">", "&gt;")


def frontmatter(title: str, description: str, icon: str) -> str:
    """Return the MDX frontmatter block for a page (title, description, icon)."""
    # Quote to keep YAML happy regardless of punctuation in the values.
    return f'---\ntitle: "{title}"\ndescription: "{description}"\nicon: "{icon}"\n---\n'


def table_code(value) -> str:
    """Return a backtick code cell safe inside a Markdown table.

    Literal pipes in the value (e.g. ``list[str] | None``) are escaped so they
    don't split columns.
    """
    return "`" + str(value).replace("|", "\\|") + "`"


def table_text(text: str) -> str:
    """Prose safe inside a Markdown table cell."""
    return mdx_escape_prose(text.replace("\n", " ")).replace("|", "\\|")
