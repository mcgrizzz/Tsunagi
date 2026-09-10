import base64
import json
from typing import Callable, Iterable, List, Optional, Tuple, TypeVar

T = TypeVar("T")

def _b64u_encode(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode("utf-8")).decode("ascii")

def _b64u_decode(s: str) -> dict:
    return json.loads(base64.b64decode(s.encode("ascii"), altchars=b"-_", validate=True).decode("utf-8"))

def decode_cursor(cursor: Optional[str], *, key_type: type = int) -> dict:
    """Decode an opaque continuation token, rejecting malformed state."""
    if cursor is None:
        return {}
    try:
        if not isinstance(cursor, str) or not cursor:
            raise ValueError
        state = _b64u_decode(cursor)
        if not isinstance(state, dict) or set(state) != {"last_key"}:
            raise ValueError
        key = state["last_key"]
        # bool is an int subclass, but never a valid resource ID.
        if type(key) is not key_type:
            raise ValueError
        if key_type is int and not 0 <= key <= 2**63 - 1:
            raise ValueError
        if key_type is str and not key:
            raise ValueError
        return state
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid pagination cursor. Use next_cursor from the previous response, or omit cursor to start over.") from exc


def encode_cursor(state: dict) -> str:
    return _b64u_encode(state)

def paginate_keyset(
    items: Iterable[T],
    limit: int,
    cursor: Optional[str],
    key_fn: Callable[[T], int],
) -> Tuple[List[T], Optional[str]]:
    state = decode_cursor(cursor)
    last_key = state.get("last_key")

    lim = max(1, int(limit) if limit is not None else 1)
    out: List[T] = []
    page_last: Optional[int] = None
    more = False

    for it in items:
        k = key_fn(it)
        if last_key is not None and k <= last_key:
            continue
        if len(out) < lim:
            out.append(it)
            page_last = k
        else:
            more = True
            break

    next_cursor = encode_cursor({"last_key": page_last}) if more else None
    return out, next_cursor
