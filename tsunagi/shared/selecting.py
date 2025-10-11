from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from glom import glom
from glom.core import T, Coalesce
from lark import Lark, Transformer, v_args
from lark.visitors import Discard
from .schemas.wrappers import Scalar


# GRAMMAR NOTES
# - ":" = alias (rename output key):  name:alias, arr[]:alias, arr[].child:alias
# - "[]" = iterate array; "." = pluck a child; "(...)" = multi-pluck per element
# - Multi-pluck aliasing:
#     • per-item inside () → (name:nm, ord:ix)
#     • optional group alias after () → arr[].(...):group_alias
# - Missing values: scalar→None, array→[], missing child in pluck→None
#
# Examples:
#   flds[]                    # copy list
#   flds[].name:labels        # pluck one field with alias
#   flds[].(name:nm,ord:ix):fields  # multi-pluck with per-item + group alias

_SELECT_GRAMMAR = r"""
start: sel ("," sel)*

?sel  : scalar
      | arr_copy
      | arr_child
      | arr_multi

# Scalars
scalar: NAME alias?                              -> scalar

# Arrays
arr_copy : NAME ARR alias?                       -> arr_copy
arr_child: NAME ARR DOT NAME alias?              -> arr_child
arr_multi: NAME ARR DOT LP group_items RP alias? -> arr_multi

# Common pieces
group_items: group_item ("," group_item)*
group_item : NAME alias?                         -> group_item
alias      : ":" NAME                            -> alias

# Tokens
ARR  : "[]"
DOT  : "."
LP   : "("
RP   : ")"
NAME : /[A-Za-z_][A-Za-z0-9_]*/

%ignore " "
"""

@dataclass
class SelectScalar:
    path: Tuple[str, ...]
    as_name: Optional[str]

@dataclass
class SelectArrayPluck:
    base: Tuple[str, ...]           # ("flds",)
    child: Optional[Tuple[str, ...]]  # None or ("name",)
    as_name: Optional[str]

@dataclass
class SelectArrayMulti:
    base: Tuple[str, ...]
    # [ ( ("name",), "nm"|None ), ( ("ord",), "ix"|None ), ... ]
    children: List[Tuple[Tuple[str, ...], Optional[str]]]
    as_name: Optional[str]

SelectNode = Union[SelectScalar, SelectArrayPluck, SelectArrayMulti]

@v_args(inline=True)
class _SelectTransformer(Transformer):

    def ARR(self, _): return Discard
    def DOT(self, _): return Discard
    def LP(self, _):  return Discard
    def RP(self, _):  return Discard
    
    # helpers
    def alias(self, name_tok):
        return str(name_tok)

    # start
    def start(self, *sels):
        return list(sels)

    # scalars
    def scalar(self, name_tok, alias_tok=None):
        name = str(name_tok)
        alias = str(alias_tok) if alias_tok else None
        return SelectScalar(path=(name,), as_name=alias)

    # arrays
    def arr_copy(self, base_tok, alias_tok=None):
        return SelectArrayPluck(base=(str(base_tok),), child=None,
                                as_name=(str(alias_tok) if alias_tok else None))

    def arr_child(self, base_tok, child_tok, alias_tok=None):
        return SelectArrayPluck(base=(str(base_tok),), child=(str(child_tok),),
                                as_name=(str(alias_tok) if alias_tok else None))

    def group_item(self, name_tok, alias_tok=None):
        return ((str(name_tok),), (str(alias_tok) if alias_tok else None))

    def group_items(self, first, *rest):
        return [first, *rest]

    def arr_multi(self, base_tok, items, alias_tok=None):
        return SelectArrayMulti(base=(str(base_tok),), children=items,
                                as_name=(str(alias_tok) if alias_tok else None))

_parser = Lark(_SELECT_GRAMMAR, parser="lalr", maybe_placeholders=False)


class SelectParseError(ValueError): ...
class SelectValidationError(ValueError): ...

def parse_select_csv(select_text: str) -> List[SelectNode]:
    if not select_text:
        return []
    try:
        tree = _parser.parse(select_text)
        nodes: List[SelectNode] = _SelectTransformer().transform(tree)
        return nodes
    except Exception as e:
        raise SelectParseError(f"Malformed select: {e}")
    
# def validate_select(
#     nodes: Sequence[SelectNode],
#     allowed: Dict[Tuple[str, ...], Sequence[str]]
# ) -> None:
#     """
#     Validate node paths against an 'allowed' table like:
#       {
#         (): ["id","name","fields","templates"],
#         ("fields",): ["name","ord"],
#         ("templates",): ["name"]
#       }
#     """
#     top_allowed = set(allowed.get((), []))
#     for n in nodes:
#         if isinstance(n, SelectScalar):
#             key = n.path[0]
#             if key not in top_allowed:
#                 allowed_list = ", ".join(sorted(top_allowed))
#                 raise SelectValidationError(f"Invalid select key '{key}' (allowed: {allowed_list})")
#         elif isinstance(n, SelectArrayPluck):
#             base_key = n.base[0]
#             if base_key not in top_allowed:
#                 allowed_list = ", ".join(sorted(top_allowed))
#                 raise SelectValidationError(f"Invalid select key '{base_key}' (allowed: {allowed_list})")
#             if n.child:
#                 child_allowed = set(allowed.get(n.base, []))
#                 child = n.child[0]
#                 if child not in child_allowed:
#                     allowed_child = ", ".join(sorted(child_allowed)) or "<none>"
#                     raise SelectValidationError(
#                         f"Invalid nested key '{base_key}[].{child}' (allowed under {base_key}: {allowed_child})"
#                     )

def _as_iterable_list(base_path: Tuple[str, ...]):
    """
    Build a glom spec that yields a safe list:
      - If base is missing → []
      - If base is not a list but truthy scalar → [that] (optional behavior, see comment)
      - If base is None/Falsey → []
    For strict-list-only behavior, change the second Coalesce default to [] instead of [T].
    """
    # Coalesce the base path to [] if missing at all
    base = Coalesce(base_path, default=[])
    # If it's not iterable, wrap singletons into a list; otherwise leave as-is.
    # If you want to be strict, use: Coalesce(base, default=[])
    return Coalesce(base, default=[T])

def _node_to_glom_spec(n: SelectNode):
    if isinstance(n, SelectScalar):
        return (n.as_name or n.path[-1]), tuple(n.path)

    if isinstance(n, SelectArrayPluck):
        alias = n.as_name or n.base[-1]
        safe = _as_iterable_list(tuple(n.base))
        if n.child is None:
            return alias, safe
        return alias, (safe, [Coalesce(tuple(n.child), default=None)])

    if isinstance(n, SelectArrayMulti):
        alias = n.as_name or n.base[-1]
        safe = _as_iterable_list(tuple(n.base))
        elem_spec = { (a or p[-1]): Coalesce(tuple(p), default=None)
                      for (p, a) in n.children }
        return alias, (safe, [elem_spec])

    raise RuntimeError(f"Unknown node: {n!r}")

        
def project_scalars(obj: Mapping[str, Any], nodes: Sequence[SelectNode]) -> Dict[str, Any]:
    """
    Phase A projector with array plucks powered by glom:
      - Scalars: straight tuple path (('name',))
      - Array copy: ('fields',)
      - Array pluck: ('fields', [Coalesce(('name',), default=None)])
    If no nodes are provided, return a shallow copy of the object.
    """
    if not nodes:
        return dict(obj)

    # Build a dict spec: { alias: subspec, ... } so we call glom exactly once per row.
    spec: Dict[str, object] = {}
    for n in nodes:
        alias, subspec = _node_to_glom_spec(n)
        spec[alias] = subspec

    # Run glom once; default=None ensures a missing top-level path yields None
    try:
        return glom(obj, spec, default=None)
    except Exception as e:
        raise SelectValidationError(f"Projection failed: {e}")

def _is_scalar(value: Any) -> bool:
    return isinstance(value, Scalar)


def maybe_flatten(projected_rows: List[Dict[str, Any]], nodes: Sequence[SelectNode], shape: str) -> List[Any]:
    shape = (shape or "auto").lower()
    if not nodes or shape == "object":
        return projected_rows

    if len(nodes) != 1:
        if shape == "scalar":
            raise SelectValidationError("shape=scalar requires exactly one selected field")
        return projected_rows

    only = nodes[0]
    key = (only.as_name or (only.path[-1] if isinstance(only, SelectScalar) else only.base[-1]))
    values = [row.get(key) for row in projected_rows]

    if shape == "scalar":
        if not all(_is_scalar(v) for v in values):
            raise SelectValidationError("shape=scalar requires the selected field to be a scalar")
        return values

    if all(_is_scalar(v) for v in values):
        return values
    return projected_rows