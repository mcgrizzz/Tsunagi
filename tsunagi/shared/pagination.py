import base64, json
from typing import Callable, Iterable, List, Tuple, TypeVar, Optional

T = TypeVar("T")

def _b64u_encode(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode("utf-8")).decode("ascii")

def _b64u_decode(s: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(s.encode("ascii")).decode("utf-8"))

def decode_cursor(cursor: Optional[str]) -> dict:
    if not cursor:
        return {}
    try:
        return _b64u_decode(cursor)
    except Exception:
        # Treat bad cursors as empty to keep UX forgiving (you can tighten later)
        return {}

def encode_cursor(state: dict) -> str:
    return _b64u_encode(state)

def paginate_keyset(
    items: Iterable[T],
    limit: int,
    cursor: Optional[str],
    key_fn: Callable[[T], int],
) -> Tuple[List[T], Optional[str]]:
    state = decode_cursor(cursor) or {}
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
