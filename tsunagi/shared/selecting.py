from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from glom import glom
from glom.core import T, Coalesce
from lark import Lark, Transformer, v_args
from lark.visitors import Discard
from lark.exceptions import UnexpectedInput
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

%import common.WS
%ignore WS
"""

@dataclass(frozen=True, slots=True)
class SelectScalar:
    path: Tuple[str, ...]
    as_name: Optional[str] = None

@dataclass(frozen=True, slots=True)
class SelectArrayPluck:
    base: Tuple[str, ...]                      # ("flds",)
    child: Optional[Tuple[str, ...]] = None    # None or ("name",)
    as_name: Optional[str] = None

@dataclass(frozen=True, slots=True)
class SelectArrayMulti:
    base: Tuple[str, ...]
    # tuple of (path, alias), where path is a tuple[str, ...]
    children: Tuple[Tuple[Tuple[str, ...], Optional[str]], ...]
    as_name: Optional[str] = None

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
        # tuple instead of list as its immutable
        return tuple(sels)

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
        return (first, *rest)  # tuple, not list

    def arr_multi(self, base_tok, items, alias_tok=None):
        return SelectArrayMulti(base=(str(base_tok),), children=tuple(items),
                                as_name=(str(alias_tok) if alias_tok else None))

_parser = Lark(_SELECT_GRAMMAR, parser="lalr", maybe_placeholders=False)

class SelectParseError(ValueError): ...
class SelectValidationError(ValueError): ...

def parse_select_csv(select_text: str) -> List[SelectNode]:
    if not select_text:
        return []
    try:
        tree = _parser.parse(select_text)
        nodes: Tuple[SelectNode, ...] = _SelectTransformer().transform(tree)
        return list(nodes)
    except UnexpectedInput as e:
        ctx = e.get_context(select_text)
        raise SelectParseError(f"Malformed select:\n{ctx}") from None
    except Exception as e:
        raise SelectParseError(f"Malformed select: {e}")

def _as_iterable_list(base_path: Tuple[str, ...]):
    """
    Build a glom spec that yields a safe list:
      - If base is missing → []
      - If base is not a list but truthy scalar → [that]
      - If base is None/Falsey → []
    NOTE: selection treats scalars as singletons; filtering is strict on [].
    """
    base = Coalesce(base_path, default=[])
    return Coalesce(base, default=[T])

# ---------- Cache directly on Tuple[SelectNode, ...] ----------

@lru_cache(maxsize=128)
def _build_spec(nodes: Tuple[SelectNode, ...]) -> Dict[str, object]:
    spec: Dict[str, object] = {}
    for n in nodes:
        if isinstance(n, SelectScalar):
            alias = n.as_name or n.path[-1]
            # before: spec[alias] = tuple(n.path)
            spec[alias] = Coalesce(tuple(n.path), default=None)

        elif isinstance(n, SelectArrayPluck):
            alias = n.as_name or n.base[-1]
            safe = _as_iterable_list(tuple(n.base))
            if n.child is None:
                spec[alias] = safe
            else:
                spec[alias] = (safe, [Coalesce(tuple(n.child), default=None)])

        elif isinstance(n, SelectArrayMulti):
            alias = n.as_name or n.base[-1]
            safe = _as_iterable_list(tuple(n.base))
            elem_spec = { (a or p[-1]): Coalesce(tuple(p), default=None)
                          for (p, a) in n.children }
            spec[alias] = (safe, [elem_spec])

        else:
            raise RuntimeError(f"Unknown node: {n!r}")
    return spec
        
def project_scalars(obj: Mapping[str, Any], nodes: Sequence[SelectNode]) -> Dict[str, Any]:
    if not nodes:
        return dict(obj)
    # nodes are frozen dataclasses -> hashable; cache key is the tuple
    spec = _build_spec(tuple(nodes))
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

# So we can do data-fetching optimization later
def selected_top_fields(select_text: Optional[str]) -> Optional[Set[str]]:
    """
    If select asks ONLY for top-level scalars (e.g., 'id,name'), return that set.
    If arrays/multiplucks/nested paths are present, return None (not cheap).
    """
    if not select_text:
        return None
    nodes: List[SelectNode] = parse_select_csv(select_text)
    if not nodes:
        return None
    tops: Set[str] = set()
    for n in nodes:
        if isinstance(n, SelectScalar):
            if len(n.path) != 1:
                return None
            tops.add(n.path[0])
        else:
            return None
    return tops
