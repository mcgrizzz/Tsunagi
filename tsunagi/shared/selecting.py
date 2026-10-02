from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import (
    Any,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    get_args,
)

from glom import glom
from glom.core import Coalesce, T
from lark import Lark, Transformer, v_args
from lark.exceptions import UnexpectedInput
from lark.visitors import Discard

from .python_compat import DATACLASS_SLOTS
from .schemas.wrappers import Scalar

# Python 3.9 cannot use typing.Union directly in isinstance().
_SCALAR_TYPES = get_args(Scalar)

# GRAMMAR NOTES
# - "[]" = iterate array; "." = pluck a child; "(...)" = multi-pluck per element
# - "[key in [...]]" = iterate only the elements whose key is one of the values
# - Output keys are the field names; there is no renaming (backlog 6.76)
# - Missing values: scalar→None, array→[], missing child in pluck→None
#
# Examples:
#   flds[]                    # copy list
#   flds[].name               # pluck one field
#   flds[].(name,ord)         # multi-pluck
#   fields[name in ["Front","Back"]]  # only the elements named Front or Back

_SELECT_GRAMMAR = r"""
start: sel ("," sel)*

?sel  : scalar
      | arr_copy
      | arr_child
      | arr_multi

# Scalars
scalar: NAME                                     -> scalar

# Arrays: "[]" for every element, or a filter for some of them
arr_copy : NAME brack                              -> arr_copy
arr_child: NAME brack DOT NAME                     -> arr_child
arr_multi: NAME brack DOT LP group_items RP        -> arr_multi
?brack   : ARR | filter
filter   : "[" NAME "in" "[" value ("," value)* "]" "]"
value    : ESCAPED_STRING -> string
         | SIGNED_INT     -> integer

# Common pieces
group_items: group_item ("," group_item)*
group_item : NAME                                -> group_item

# Tokens
ARR  : "[]"
DOT  : "."
LP   : "("
RP   : ")"
// Unicode-aware: Anki field names are routinely non-ASCII (select=単語)
NAME : /[^\W\d]\w*/

%import common.ESCAPED_STRING
%import common.SIGNED_INT
%import common.WS
%ignore WS
"""

@dataclass(frozen=True, **DATACLASS_SLOTS)
class SelectScalar:
    path: Tuple[str, ...]

# (key, allowed values): keep only the array elements whose key is one of them.
ElementFilter = Tuple[str, FrozenSet[Scalar]]

@dataclass(frozen=True, **DATACLASS_SLOTS)
class SelectArrayPluck:
    base: Tuple[str, ...]                      # ("flds",)
    child: Optional[Tuple[str, ...]] = None    # None or ("name",)
    where: Optional[ElementFilter] = None

@dataclass(frozen=True, **DATACLASS_SLOTS)
class SelectArrayMulti:
    base: Tuple[str, ...]
    children: Tuple[Tuple[str, ...], ...]      # each a path, such as ("name",)
    where: Optional[ElementFilter] = None

SelectNode = Union[SelectScalar, SelectArrayPluck, SelectArrayMulti]

@v_args(inline=True)
class _SelectTransformer(Transformer):

    def ARR(self, _): return None   # every element: no filter
    def DOT(self, _): return Discard
    def LP(self, _):  return Discard
    def RP(self, _):  return Discard

    # start
    def start(self, *sels):
        # tuple instead of list as its immutable
        return tuple(sels)

    # scalars
    def scalar(self, name_tok):
        return SelectScalar(path=(str(name_tok),))

    # arrays
    def string(self, tok):
        return json.loads(tok)

    def integer(self, tok):
        return int(tok)

    def filter(self, key_tok, *values):
        return (str(key_tok), frozenset(values))

    def arr_copy(self, base_tok, where):
        return SelectArrayPluck(base=(str(base_tok),), child=None, where=where)

    def arr_child(self, base_tok, where, child_tok):
        return SelectArrayPluck(base=(str(base_tok),), child=(str(child_tok),), where=where)

    def group_item(self, name_tok):
        return (str(name_tok),)

    def group_items(self, first, *rest):
        return (first, *rest)  # tuple, not list

    def arr_multi(self, base_tok, where, items):
        return SelectArrayMulti(base=(str(base_tok),), children=tuple(items), where=where)

_parser = Lark(_SELECT_GRAMMAR, parser="lalr", maybe_placeholders=False)

class SelectParseError(ValueError): ...
class SelectValidationError(ValueError): ...

# Stateless (pure methods), so one instance serves every parse - same as
# filtering's module-level transformer.
_transformer = _SelectTransformer()


@lru_cache(maxsize=512)
def _parse_select_cached(select_text: str) -> Tuple[SelectNode, ...]:
    return _transformer.transform(_parser.parse(select_text))


def parse_select_csv(select_text: str) -> List[SelectNode]:
    if not select_text:
        return []
    try:
        # Cached parse (nodes are immutable); fresh list per caller.
        return list(_parse_select_cached(select_text))
    except UnexpectedInput as e:
        if getattr(e, "char", None) == ":":
            # name:alias renamed the output key until 6.76.
            raise SelectParseError("select doesn't rename fields (name:alias); output keys are "
                                   "the field names, so rename them in your app") from None
        ctx = e.get_context(select_text)
        raise SelectParseError(
            f"Malformed select:\n{ctx}\n\n"
            f"Valid examples:\n"
            f"  - id,name,type (scalar fields)\n"
            f"  - flds[] (array copy)\n"
            f"  - flds[].name (pluck field from array)\n"
            f"  - flds[].(name,ord) (multi-pluck)\n"
            f"  - fields[name in [\"Front\",\"Back\"]] (only some elements)"
        ) from None
    except Exception as e:
        raise SelectParseError(f"Malformed select: {e}") from e

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

def _kept(values: List[Any], where: Optional[ElementFilter]) -> List[Any]:
    """The elements a filter keeps: mappings whose key holds one of its values.
    Anything but a list passes through, as it does for "[]"."""
    if where is None or not isinstance(values, (list, tuple)):
        return values
    key, allowed = where

    def keep(value: Any) -> bool:
        try:
            return isinstance(value, Mapping) and value.get(key) in allowed
        except TypeError:   # a list or dict under the key matches nothing
            return False
    return [v for v in values if keep(v)]

# ---------- Cache directly on Tuple[SelectNode, ...] ----------

@lru_cache(maxsize=128)
def _build_spec(nodes: Tuple[SelectNode, ...]) -> Dict[str, object]:
    spec: Dict[str, object] = {}
    for n in nodes:
        if isinstance(n, SelectScalar):
            spec[n.path[-1]] = Coalesce(tuple(n.path), default=None)

        elif isinstance(n, SelectArrayPluck):
            key = n.base[-1]
            safe = _as_iterable_list(tuple(n.base))
            if n.where is not None:
                safe = (safe, lambda values, where=n.where: _kept(values, where))
            if n.child is None:
                spec[key] = safe
            else:
                spec[key] = (safe, [Coalesce(tuple(n.child), default=None)])

        elif isinstance(n, SelectArrayMulti):
            key = n.base[-1]
            safe = _as_iterable_list(tuple(n.base))
            if n.where is not None:
                safe = (safe, lambda values, where=n.where: _kept(values, where))
            elem_spec = {p[-1]: Coalesce(tuple(p), default=None) for p in n.children}
            spec[key] = (safe, [elem_spec])

        else:
            raise RuntimeError(f"Unknown node: {n!r}")
    return spec
        
def selection_include(nodes: Sequence[SelectNode]) -> Dict[str, Any]:
    """Pydantic include mask: convert only the values the projection reads."""
    include: Dict[str, Any] = {}
    for node in nodes:
        if isinstance(node, SelectScalar):
            include[node.path[0]] = True
            continue
        base = node.base[0]
        if include.get(base) is True:
            continue
        if isinstance(node, SelectArrayPluck):
            paths = [node.child] if node.child is not None else []
        else:
            paths = list(node.children)
        if node.where is not None and paths:
            paths.append((node.where[0],))   # the filter reads its key too
        if len(node.base) != 1 or not paths or any(len(path) != 1 for path in paths):
            include[base] = True
        else:
            include.setdefault(base, {"__all__": set()})["__all__"].update(path[0] for path in paths)
    return include


def _project_simple(obj: Mapping[str, Any], nodes: Sequence[SelectNode]) -> Optional[Dict[str, Any]]:
    """Direct lookups for single-level fields and arrays of dictionaries.

    Unusual shapes retain glom's behavior, including whole-projection failure.
    This only caches query syntax elsewhere; every value comes from this row.
    """
    result = {}
    for node in nodes:
        if isinstance(node, SelectScalar):
            if len(node.path) != 1:
                return None
            result[node.path[0]] = obj.get(node.path[0])
            continue
        if not isinstance(node, (SelectArrayPluck, SelectArrayMulti)) or len(node.base) != 1:
            return None
        values = obj.get(node.base[0], [])
        if not isinstance(values, list):
            return None
        values = _kept(values, node.where)
        key = node.base[0]
        if isinstance(node, SelectArrayPluck) and node.child is None:
            result[key] = values
            continue
        if not all(isinstance(value, Mapping) for value in values):
            return None
        if isinstance(node, SelectArrayPluck):
            if len(node.child) != 1:
                return None
            result[key] = [value.get(node.child[0]) for value in values]
        else:
            if any(len(path) != 1 for path in node.children):
                return None
            result[key] = [{path[0]: value.get(path[0]) for path in node.children}
                             for value in values]
    return result


def project_scalars(obj: Mapping[str, Any], nodes: Sequence[SelectNode]) -> Dict[str, Any]:
    if not nodes:
        return dict(obj)
    try:
        result = _project_simple(obj, nodes)
        if result is not None:
            return result
        return glom(obj, _build_spec(tuple(nodes)), default=None)
    except Exception as e:
        raise SelectValidationError(f"Projection failed: {e}") from e

def _is_scalar(value: Any) -> bool:
    return isinstance(value, _SCALAR_TYPES)

def maybe_flatten(projected_rows: List[Dict[str, Any]], nodes: Sequence[SelectNode], shape: str) -> List[Any]:
    """Objects, whatever the select; shape=scalar returns the one selected
    field's bare values instead."""
    if not nodes or (shape or "object").lower() != "scalar":
        return projected_rows
    if len(nodes) != 1:
        raise SelectValidationError("shape=scalar requires exactly one selected field")

    only = nodes[0]
    key = only.path[-1] if isinstance(only, SelectScalar) else only.base[-1]
    values = [row.get(key) for row in projected_rows]
    if not all(_is_scalar(v) for v in values):
        raise SelectValidationError("shape=scalar requires the selected field to be a scalar")
    return values

def referenced_top_fields(select_text: Optional[str]) -> Optional[Set[str]]:
    """
    Every top-level field name the select touches, including array bases
    ('flds[].name' -> 'flds'). Returns None only when there is no select,
    meaning "the whole record".

    Unlike selected_top_fields (which answers "can a columns fetcher serve
    this?" and bails on arrays), this answers "which fields must be built?"
    so fetchers can skip expensive ones.
    """
    if not select_text:
        return None
    tops: Set[str] = set()
    for n in parse_select_csv(select_text):
        if isinstance(n, SelectScalar):
            tops.add(n.path[0])
        else:
            tops.add(n.base[0])
    return tops

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
