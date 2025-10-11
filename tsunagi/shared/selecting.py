from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from glom import glom
from glom.core import T, Coalesce
from lark import Lark, Transformer, v_args
from .schemas.wrappers import Scalar

_SELECT_GRAMMAR = r"""
start: sel ("," sel)*

?sel : arr_copy
     | arr_child
     | arr_copy_alias
     | arr_child_alias
     | scalar

scalar: NAME [ ":" NAME ]                   -> scalar_alias
arr_copy: NAME "[]"                         -> arr_copy
arr_child: NAME "[]" "." NAME               -> arr_child
arr_copy_alias: NAME "[]" ":" NAME          -> arr_copy_alias
arr_child_alias: NAME "[]" "." NAME ":" NAME-> arr_child_alias

NAME: /[A-Za-z_][A-Za-z0-9_]*/
%ignore " "
"""

@dataclass
class SelectScalar:
    path: Tuple[str, ...]
    as_name: Optional[str]  # alias or None

@dataclass
class SelectArrayPluck:
    base: Tuple[str, ...]           # e.g. ("fields",)
    child: Optional[Tuple[str, ...]]  # e.g. ("name",) or None for [] copy
    as_name: Optional[str]

SelectNode = Union[SelectScalar, SelectArrayPluck]

@v_args(inline=True)
class _SelectTransformer(Transformer):
    def start(self, *sels):
        return list(sels)

    def scalar_alias(self, name_token, alias_token=None):
        name = str(name_token)
        alias = str(alias_token) if alias_token else None
        return SelectScalar(path=(name,), as_name=alias)

    # flds[]                -> base=flds, child=None, alias=None
    def arr_copy(self, base_token):
        return SelectArrayPluck(base=(str(base_token),), child=None, as_name=None)

    # flds[].name           -> base=flds, child=name, alias=None
    def arr_child(self, base_token, child_token):
        return SelectArrayPluck(base=(str(base_token),), child=(str(child_token),), as_name=None)

    # flds[]:fields         -> base=flds, child=None, alias=fields   <-- your failing case
    def arr_copy_alias(self, base_token, alias_token):
        return SelectArrayPluck(base=(str(base_token),), child=None, as_name=str(alias_token))

    # flds[].name:alias
    def arr_child_alias(self, base_token, child_token, alias_token):
        return SelectArrayPluck(
            base=(str(base_token),),
            child=(str(child_token),),
            as_name=str(alias_token),
        )


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
    
def validate_select(
    nodes: Sequence[SelectNode],
    allowed: Dict[Tuple[str, ...], Sequence[str]]
) -> None:
    """
    Validate node paths against an 'allowed' table like:
      {
        (): ["id","name","fields","templates"],
        ("fields",): ["name","ord"],
        ("templates",): ["name"]
      }
    """
    top_allowed = set(allowed.get((), []))
    for n in nodes:
        if isinstance(n, SelectScalar):
            key = n.path[0]
            if key not in top_allowed:
                allowed_list = ", ".join(sorted(top_allowed))
                raise SelectValidationError(f"Invalid select key '{key}' (allowed: {allowed_list})")
        elif isinstance(n, SelectArrayPluck):
            base_key = n.base[0]
            if base_key not in top_allowed:
                allowed_list = ", ".join(sorted(top_allowed))
                raise SelectValidationError(f"Invalid select key '{base_key}' (allowed: {allowed_list})")
            if n.child:
                child_allowed = set(allowed.get(n.base, []))
                child = n.child[0]
                if child not in child_allowed:
                    allowed_child = ", ".join(sorted(child_allowed)) or "<none>"
                    raise SelectValidationError(
                        f"Invalid nested key '{base_key}[].{child}' (allowed under {base_key}: {allowed_child})"
                    )

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

def _node_to_glom_spec(n: SelectNode) -> Tuple[str, object]:
    """
    Compile a SelectNode into a (alias, glom_spec) pair with tolerant behavior:
      - Missing scalar -> None
      - Missing array  -> []
      - Array pluck on missing/ill-typed base -> []
    """
    if isinstance(n, SelectScalar):
        alias = n.as_name or n.path[-1]
        # Scalars: missing key becomes None thanks to glom(default=None) at call site.
        return alias, tuple(n.path)

    # Array cases
    alias = n.as_name or n.base[-1]
    base_path = tuple(n.base)

    # Ensure we always have a list to map over ([] when missing)
    safe_list_spec = _as_iterable_list(base_path)

    if n.child is None:
        # 'fields[]' → return the (possibly coerced) list as-is
        return alias, safe_list_spec

    # 'fields[].name' → pluck, defaulting each element's child to None
    inner = Coalesce(tuple(n.child), default=None)
    # Map 'inner' over the safe list
    return alias, (safe_list_spec, [inner])

        
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
        # Convert confusing glom errors into a clean 400
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