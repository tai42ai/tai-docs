#!/usr/bin/env python3
"""Dump the ``tai`` command tree as JSON.

This runs inside an environment where the ``tai`` console script is installed
(the tai42/core/skeleton env resolves the full tree: skeleton pulls in
tai42-cli). It resolves the ``tai`` ``console_scripts`` entry point and loads
the exact compiled click application operators run, then walks the whole command
tree -- every group, every command, at every depth -- emitting a JSON document on
stdout that ``gen_cli.py`` renders to MDX.

Every field traces to the real command objects: help text, usage pieces, and
option/argument metadata all come from the live click ``Context`` the runtime
itself uses to render ``--help``. Nothing is invented here.
"""

from __future__ import annotations

import importlib.metadata
import json
import sys

import click


def _clean(text: str | None) -> str:
    return (text or "").strip()


def _param_dict(param, ctx: click.Context) -> dict | None:
    """Describe one option/argument, or None for hidden params and --help."""
    if getattr(param, "hidden", False):
        return None
    if param.name == "help":
        return None
    try:
        metavar = param.make_metavar(ctx)
    except TypeError:  # older click signature
        metavar = param.make_metavar()
    kind = "argument" if param.param_type_name == "argument" else "option"
    default = getattr(param, "default", None)
    # Sentinels and callables are not representable defaults; drop them.
    if default is not None and (callable(default) or type(default).__name__ == "Sentinel"):
        default = None
    return {
        "kind": kind,
        "name": param.name,
        "opts": list(getattr(param, "opts", []) or []),
        "secondary_opts": list(getattr(param, "secondary_opts", []) or []),
        "metavar": metavar,
        "required": bool(param.required),
        "default": default if isinstance(default, (str, int, float, bool)) else None,
        "help": _clean(getattr(param, "help", None)),
        "is_flag": bool(getattr(param, "is_flag", False)) or bool(getattr(param, "secondary_opts", [])),
    }


def _walk(command, name: str, path: list[str], parent: click.Context) -> dict:
    ctx = click.Context(command, info_name=name, parent=parent)
    params = []
    for param in command.get_params(ctx):
        described = _param_dict(param, ctx)
        if described is not None:
            params.append(described)
    node = {
        "name": name,
        "path": path,
        "help": _clean(command.help),
        "short_help": _clean(command.get_short_help_str(limit=200)),
        "usage": command.collect_usage_pieces(ctx),
        "params": params,
        "commands": [],
    }
    subcommands = getattr(command, "commands", None) or {}
    for sub_name in sorted(subcommands):
        node["commands"].append(_walk(subcommands[sub_name], sub_name, [*path, sub_name], ctx))
    return node


def _resolve_tai_app() -> click.Command:
    """Load the compiled click app behind the installed ``tai`` console script.

    The dumped tree is exactly what operators run, wherever the app lives. A
    missing entry point is a fail-loud contract: raise so ``main`` exits non-zero
    and writes no placeholder tree."""
    matches = [ep for ep in importlib.metadata.entry_points(group="console_scripts") if ep.name == "tai"]
    if not matches:
        raise LookupError(
            "no 'tai' console-script entry point is installed; run inside an env "
            "where tai42-cli (and, for the full tree, tai42-skeleton) resolves"
        )
    return matches[0].load()


def build_tree() -> dict:
    return _walk(_resolve_tai_app(), "tai", ["tai"], parent=None)


def main() -> int:
    try:
        tree = build_tree()
    except LookupError as exc:
        print(f"_cli_introspect: {exc}", file=sys.stderr)
        return 1
    json.dump(tree, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
