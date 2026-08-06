# tsunagi/shared/filtering.py
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache, partial
from itertools import chain
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Tuple,
)

from lark import Lark, Transformer, v_args
from lark.exceptions import UnexpectedInput
from lark.visitors import Discard

# Grammar for ONE clause. Multiple ?where=... params → AND.
# Examples:
#   id==123
#   name~="basic"
#   did in[1,2,3]
#   flds[].name=="Front"
#   tmpls[].ord>=1
#   flds[].name not in["Front","Back"]
_WHERE_GRAMMAR = r"""
start: clause

?clause : path OP value                 -> binop
        | path "in" list                -> inop
        | path "not" "in" list          -> notinop

path  : NAME (ARR | DOT NAME)*

value : STRING            -> sval
      | SIGNED_NUMBER     -> nval
      | TRUE              -> tval
      | FALSE             -> fval
      | NULL              -> nll
      | NAME              -> ident

list  : LBRACK [value ("," value)*] RBRACK

ARR   : "[]"
DOT   : "."
OP    : "==" | "!=" | "~=" | ">=" | "<=" | ">" | "<"

LBRACK: "["
RBRACK: "]"

// Priority 2 so these beat NAME; \b stops them matching prefixes (e.g. "truely")
TRUE.2  : /true\b/i
FALSE.2 : /false\b/i
NULL.2  : /null\b/i

// Unicode-aware: Anki field names and values are routinely non-ASCII
// (e.g. select=単語, where=fields[].value==犬). \w is unicode by default in
// Python; excluding a leading digit keeps numbers matching SIGNED_NUMBER.
NAME : /[^\W\d]\w*/
%import common.SIGNED_NUMBER
%import common.WS
%import common.ESCAPED_STRING -> STRING
%ignore WS
"""

@dataclass(frozen=True, slots=True)
class Clause:
    tokens: Tuple[str, ...]   # e.g., ("flds","[]","name")
    op: str                   # OP or "in"/"not in"
    value: Any                # scalar or list

class WhereParseError(ValueError): ...

@v_args(inline=True)
class _WhereTransformer(Transformer):
    # NOTE: ARR ("[]") must NOT be discarded - path() relies on it to mark
    # array traversal in the compiled accessor tokens.
    def DOT(self, _): return Discard
    def LBRACK(self, _): return Discard
    def RBRACK(self, _): return Discard

    def start(self, clause): return clause

    def path(self, first, *rest):
        parts: List[str] = [str(first)]
        for r in rest:
            s = str(r)
            parts.append("[]" if s == "[]" else s)
        return tuple(parts)

    def sval(self, s):     # "quoted"
        return s[1:-1]
    def ident(self, n):    # bare identifier → string
        return str(n)
    def nval(self, n):
        txt = str(n)
        if "." in txt or "e" in txt or "E" in txt:
            try: return float(txt)
            except Exception: return txt
        try: return int(txt)
        except Exception: return txt
    def tval(self, _): return True
    def fval(self, _): return False
    def nll(self, _): return None

    def list(self, *vals): return list(vals)

    def binop(self, path, op, value):
        return Clause(tokens=tuple(path), op=str(op), value=value)
    def inop(self, path, values):
        return Clause(tokens=tuple(path), op="in", value=values)
    def notinop(self, path, values):
        return Clause(tokens=tuple(path), op="not in", value=values)

_parser = Lark(_WHERE_GRAMMAR, parser="lalr", maybe_placeholders=False)
_transformer = _WhereTransformer()

@lru_cache(maxsize=512)
def parse_where(clause_text: str) -> Clause:
    # Cached: one request parses the same clause up to ~5 times (planner
    # tiers, wants computation, predicate build). Clause is frozen, so
    # sharing the instance is safe. Parse errors are not cached (lru_cache
    # does not memoize raises), so malformed input still reports each time.
    try:
        tree = _parser.parse(clause_text)
        out = _transformer.transform(tree)
        if not isinstance(out, Clause):
            raise WhereParseError(f"Internal: expected Clause, got {type(out).__name__}")
        return out
    except UnexpectedInput as e:
        ctx = e.get_context(clause_text)
        raise WhereParseError(
            f"Malformed where clause {clause_text!r}:\n{ctx}\n\n"
            f"Valid examples:\n"
            f"  - id==123\n"
            f"  - name~=\"Basic\"\n"
            f"  - type>=0\n"
            f"  - id in [1,2,3]\n"
            f"  - flds[].name==\"Front\"\n"
            f"  - name not in [\"Cloze\",\"Basic\"]"
        ) from None
    except Exception as e:
        raise WhereParseError(f"Malformed where clause {clause_text!r}: {e}") from e

# ----- Accessors (compiled & cached) -----

Accessor = Callable[[Mapping[str, Any]], Iterable[Any]]

@lru_cache(maxsize=256)
def _compile_accessor(tokens: Tuple[str, ...]) -> Accessor:
    has_array = "[]" in tokens
    first = tokens[0] if tokens else None

    def _walk(cur: Any, i: int) -> Iterator[Any]:
        if i >= len(tokens):
            yield cur
            return
        tok = tokens[i]
        if tok == "[]":
            if isinstance(cur, list):
                for el in cur:
                    yield from _walk(el, i + 1)
            # strict: scalars produce no elements when [] requested
            return
        if isinstance(cur, Mapping) and tok in cur:
            yield from _walk(cur[tok], i + 1)
        else:
            return

    def _access(obj: Mapping[str, Any]) -> Iterable[Any]:
        if not tokens:
            return ()
        if not has_array:
            cur: Any = obj
            for t in tokens:
                if isinstance(cur, Mapping) and t in cur:
                    cur = cur[t]
                else:
                    return ()
            return (cur,) if cur is not None else ()
        if first is None or first == "[]" or first not in obj:
            return ()
        return _walk(obj[first], 1)

    return _access

# ----- Operators -----

def _eq_strict(a: Any, b: Any) -> bool:
    if isinstance(a, bool) ^ isinstance(b, bool):
        return False
    return a == b

def _any_eq(vals: Iterable[Any], x: Any) -> bool:
    return any(_eq_strict(v, x) for v in vals)

def _none_eq(vals: Iterable[Any], x: Any) -> bool:
    return all(not _eq_strict(v, x) for v in vals)

def _substr(vals: Iterable[Any], needle: Any) -> bool:
    if not isinstance(needle, str): 
        return False
    n = needle.casefold()
    return any(isinstance(v, str) and n in v.casefold() for v in vals)

def _cmp(vals: Iterable[Any], x: Any, op: str) -> bool:
    # Only compare values of exactly the same type
    vs = (v for v in vals if type(v) is type(x))
    if op == ">":  return any(v >  x for v in vs)
    if op == ">=": return any(v >= x for v in vs)
    if op == "<":  return any(v <  x for v in vs)
    if op == "<=": return any(v <= x for v in vs)
    return False

def _any_in(vals: Iterable[Any], coll: Any) -> bool:
    if not isinstance(coll, list):
        return False
    try:
        s = set(coll)
        for v in vals:
            try:
                if v in s:
                    return True
            except TypeError:
                # v unhashable → fallback to linear scan
                if any(_eq_strict(v, c) for c in coll):
                    return True
        return False
    except TypeError:
        # coll has unhashables → linear scan
        return any(any(_eq_strict(v, c) for c in coll) for v in vals)

def _none_in(vals: Iterable[Any], coll: Any) -> bool:
    if not isinstance(coll, list):
        return False
    try:
        s = set(coll)
        for v in vals:
            try:
                if v in s:
                    return False
            except TypeError:
                if any(_eq_strict(v, c) for c in coll):
                    return False
        return True
    except TypeError:
        return all(all(not _eq_strict(v, c) for c in coll) for v in vals)

_OPS: Dict[str, Callable[..., bool]] = {
    "==":  _any_eq,
    "!=":  _none_eq,     # NONE equals
    "~=":  _substr,
    ">":   partial(_cmp, op=">"),
    ">=":  partial(_cmp, op=">="),
    "<":   partial(_cmp, op="<"),
    "<=":  partial(_cmp, op="<="),
    "in":      _any_in,
    "not in":  _none_in, # NONE in
}

# Small helper to peek without materializing the whole iterator
def _peek(it: Iterable[Any]) -> tuple[bool, Iterable[Any]]:
    it = iter(it)
    try:
        first = next(it)
    except StopIteration:
        return False, ()
    return True, chain((first,), it)

def build_predicate(where_params: List[str]) -> Callable[[Mapping[str, Any]], bool]:
    """
    Compile a predicate that ANDs all where clauses.
    Missing paths -> no values -> clause fails (consistent, predictable).
    """
    clauses = [parse_where(w) for w in where_params]
    compiled: List[Tuple[Accessor, str, Any]] = [
        (_compile_accessor(tuple(c.tokens)), c.op, c.value) for c in clauses
    ]

    def _pred(obj: Mapping[str, Any]) -> bool:
        for accessor, op, val in compiled:
            has_any, vals = _peek(accessor(obj))
            if not has_any:
                return False
            if not _OPS[op](vals, val):
                return False
        return True

    return _pred
