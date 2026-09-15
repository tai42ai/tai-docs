"""Render a TypeDoc type node to a TypeScript type string.

Includes external-alias recovery: TypeScript resolves some type aliases away
before TypeDoc sees them — notably a computed alias like
``ApiClient = ReturnType<typeof createApiClient>`` — so at every use site TypeDoc
serialises the FULL structural object literal instead of the name. That leaks
internal impl types, produces multi-thousand-char one-line signatures, and hits
TypeDoc's depth limit (literal ``...`` ellipses).

The name is recovered via TypeDoc's ``symbolIdMap``: both the anonymous inline
literal and the documented export carry a symbol origin (package + source path).
When an EXTERNAL source file exports exactly one documented type, an anonymous
object literal originating from that file IS that type — so its name is rendered
(and cross-linked) instead of expanded. Rendering stops at the outer literal, so
nested member literals from the same file are never reached and never mis-named.
The alias context is set once per ``build_reference`` run via
``init_alias_context`` and is deterministic within it.
"""

from __future__ import annotations

from collections.abc import Callable

_SYMBOL_ID_MAP: dict[str, dict] = {}
_ALIAS_ORIGIN_TO_NAME: dict[tuple[str, str], str] = {}


def init_alias_context(project: dict, exports: list[tuple[dict, str]]) -> None:
    """Set the per-run alias state from a TypeDoc project and its exports.

    Captures the ``symbolIdMap`` used to recover external-type origins, and the
    map from each single-export external origin to that type's name.
    """
    global _SYMBOL_ID_MAP, _ALIAS_ORIGIN_TO_NAME
    _SYMBOL_ID_MAP = project.get("symbolIdMap") or {}
    _ALIAS_ORIGIN_TO_NAME = _build_alias_origins(exports)


def _origin_of(decl: dict) -> tuple[str, str] | None:
    """The (packageName, packagePath) symbol origin of a reflection, or None."""
    sid = _SYMBOL_ID_MAP.get(str(decl.get("id")))
    if not sid:
        return None
    pkg = sid.get("packageName")
    path = sid.get("packagePath")
    if pkg is None or path is None:
        return None
    return (pkg, path)


def _collapsed_alias(decl: dict) -> str | None:
    """Return the NAME of a documented external type TypeDoc expanded inline, else None.

    ``decl`` matches when it is an inline object literal that is really a
    documented, externally-defined named type (TypeDoc expanded it because
    TypeScript resolved the alias away).
    """
    if not decl.get("children"):
        return None
    origin = _origin_of(decl)
    if origin is None:
        return None
    return _ALIAS_ORIGIN_TO_NAME.get(origin)


def _build_alias_origins(exports: list[tuple[dict, str]]) -> dict[tuple[str, str], str]:
    """Map each external single-export source origin to that type's name.

    Local (``@tai42/studio-sdk``) types already render by reference, so they are
    excluded — only re-exported external types (whose aliases TypeDoc expands)
    need recovering.
    """
    origin_names: dict[tuple[str, str], set[str]] = {}
    for refl, _module in exports:
        origin = _origin_of(refl)
        if origin is None or origin[0] == "@tai42/studio-sdk":
            continue
        origin_names.setdefault(origin, set()).add(refl["name"])
    return {origin: next(iter(names)) for origin, names in origin_names.items() if len(names) == 1}


def _type_params_str(container: dict | None) -> str:
    """Render a reflection's / signature's ``<T extends C = D, …>`` type-parameter list.

    Returns "" when there are none. Without this a generic symbol renders a
    free, undeclared ``T`` in its signature.
    """
    tparams = (container or {}).get("typeParameters") or []
    if not tparams:
        return ""
    parts: list[str] = []
    for tp in tparams:
        text = tp.get("name", "")
        constraint = tp.get("type")
        if constraint:
            text += f" extends {type_str(constraint)}"
        default = tp.get("default")
        if default:
            text += f" = {type_str(default)}"
        parts.append(text)
    return "<" + ", ".join(parts) + ">"


def _wrap(rendered: str, source: dict | None) -> str:
    """Parenthesise a compound type before an array/postfix operator."""
    if isinstance(source, dict) and source.get("type") in ("union", "intersection", "reflection"):
        return f"({rendered})"
    return rendered


def _template_literal_str(t: dict) -> str:
    head = t.get("head", "")
    tail = t.get("tail", []) or []
    parts = [head]
    for type_part, literal in tail:
        parts.append("${" + type_str(type_part) + "}")
        parts.append(literal)
    return "".join(parts)


def _reflection_type_str(decl: dict) -> str:
    """Render an inline reflection type: a function type, an index signature, or an object type literal.

    Kept compact — the full shape lives on the named interface/type-alias when
    there is one.
    """
    sigs = decl.get("signatures")
    if sigs:
        sig = sigs[0]
        params = ", ".join(_param_str(p) for p in sig.get("parameters", []) or [])
        return f"{_type_params_str(sig)}({params}) => {type_str(sig.get('type'))}"
    children = decl.get("children")
    if children:
        fields = []
        for child in children:
            opt = "?" if (child.get("flags") or {}).get("isOptional") else ""
            fields.append(f"{child.get('name')}{opt}: {type_str(child.get('type'))}")
        return "{ " + "; ".join(fields) + " }"
    index_sig = decl.get("indexSignatures")
    if index_sig:
        sig = index_sig[0]
        key = sig.get("parameters", [{}])[0]
        return f"{{ [{key.get('name', 'key')}: {type_str(key.get('type'))}]: {type_str(sig.get('type'))} }}"
    return "object"


def _param_str(param: dict) -> str:
    name = param.get("name", "")
    if name == "__namedParameters":
        name = "props"
    rest = "..." if (param.get("flags") or {}).get("isRest") else ""
    opt = "?" if (param.get("flags") or {}).get("isOptional") else ""
    annotated = type_str(param.get("type"))
    return f"{rest}{name}{opt}: {annotated}"


# --------------------------------------------------------------------------- #
# Per-kind type renderers, dispatched by the node's ``type`` discriminant.
# --------------------------------------------------------------------------- #


def _render_intrinsic(t: dict) -> str:
    return t.get("name", "unknown")


def _render_literal(t: dict) -> str:
    value = t.get("value")
    if isinstance(value, str):
        return f'"{value}"'
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_reference(t: dict) -> str:
    name = t.get("name", "unknown")
    args = t.get("typeArguments") or []
    if args:
        return f"{name}<{', '.join(type_str(a) for a in args)}>"
    return name


def _render_array(t: dict) -> str:
    inner = type_str(t.get("elementType"))
    return f"{_wrap(inner, t.get('elementType'))}[]"


def _render_union(t: dict) -> str:
    return " | ".join(type_str(x) for x in t.get("types", []))


def _render_intersection(t: dict) -> str:
    return " & ".join(type_str(x) for x in t.get("types", []))


def _render_tuple(t: dict) -> str:
    return "[" + ", ".join(type_str(x) for x in t.get("elements", [])) + "]"


def _render_type_operator(t: dict) -> str:
    return f"{t.get('operator', '')} {type_str(t.get('target'))}".strip()


def _render_query(t: dict) -> str:
    return f"typeof {type_str(t.get('queryType'))}"


def _render_indexed_access(t: dict) -> str:
    return f"{type_str(t.get('objectType'))}[{type_str(t.get('indexType'))}]"


def _render_reflection(t: dict) -> str:
    decl = t.get("declaration") or {}
    alias = _collapsed_alias(decl)
    if alias is not None:
        return alias
    return _reflection_type_str(decl)


def _render_predicate(t: dict) -> str:
    return f"{t.get('name', '')} is {type_str(t.get('targetType'))}"


def _render_template_literal(t: dict) -> str:
    return "`" + _template_literal_str(t) + "`"


def _render_optional(t: dict) -> str:
    return f"{type_str(t.get('elementType'))}?"


def _render_rest(t: dict) -> str:
    return f"...{type_str(t.get('elementType'))}"


def _render_named_tuple_member(t: dict) -> str:
    opt = "?" if t.get("isOptional") else ""
    return f"{t.get('name', '')}{opt}: {type_str(t.get('element'))}"


def _render_conditional(t: dict) -> str:
    return (
        f"{type_str(t.get('checkType'))} extends {type_str(t.get('extendsType'))} "
        f"? {type_str(t.get('trueType'))} : {type_str(t.get('falseType'))}"
    )


def _render_unknown(t: dict) -> str:
    return t.get("name", "unknown")


_TYPE_RENDERERS: dict[str, Callable[[dict], str]] = {
    "intrinsic": _render_intrinsic,
    "literal": _render_literal,
    "reference": _render_reference,
    "array": _render_array,
    "union": _render_union,
    "intersection": _render_intersection,
    "tuple": _render_tuple,
    "typeOperator": _render_type_operator,
    "query": _render_query,
    "indexedAccess": _render_indexed_access,
    "reflection": _render_reflection,
    "predicate": _render_predicate,
    "templateLiteral": _render_template_literal,
    "optional": _render_optional,
    "rest": _render_rest,
    "named-tuple-member": _render_named_tuple_member,
    "conditional": _render_conditional,
    "unknown": _render_unknown,
}


def type_str(t: dict | None) -> str:
    """Render a TypeDoc type object to a readable TypeScript type string."""
    if not isinstance(t, dict):
        return "unknown"
    handler = _TYPE_RENDERERS.get(t.get("type"))
    return handler(t) if handler else "unknown"


def collect_refs(t: dict | None, out: set[str]) -> None:
    """Collect the names of every ``reference`` type reachable from ``t``.

    Used to render a "Related types" line linking to locally documented symbols.
    """
    if isinstance(t, dict):
        # A collapsed external alias (e.g. ApiClient) links by its recovered name;
        # stop here so its expanded internal structure is not walked.
        if t.get("type") == "reflection":
            alias = _collapsed_alias(t.get("declaration") or {})
            if alias is not None:
                out.add(alias)
                return
        # Only same-package references (not type parameters) resolve to a local page.
        if (
            t.get("type") == "reference"
            and isinstance(t.get("name"), str)
            and t.get("package") == "@tai42/studio-sdk"
            and not t.get("refersToTypeParameter")
        ):
            out.add(t["name"])
        for value in t.values():
            collect_refs(value, out)
    elif isinstance(t, list):
        for item in t:
            collect_refs(item, out)
