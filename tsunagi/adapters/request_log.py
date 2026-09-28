"""
Recent requests, per client, for the settings page's "Recent requests" page
(backlog 6.4). A busy client cannot push another client's requests out of
view: each keeps its own last PER_CLIENT requests and running totals.

Clients: an app by name; a request without a key (or refused before the key
check) by its website origin, else by where it came from. Apps are never
dropped; at most MAX_KEYLESS keyless clients are kept, dropping the one idle
longest, so origins made up by a spammer can only push out each other.

Memory only: nothing is written to disk, and keys and bodies are never
recorded. The settings page reads it over Anki's pycmd bridge, so it is not
reachable over HTTP.
"""
import threading
from collections import deque
from typing import Any, Dict, List, Optional

from .settings import NO_KEY_LOCAL, NO_KEY_REMOTE

PER_CLIENT = 50
MAX_KEYLESS = 50
MAX_SHOWN = 200  # entries one read returns

_clients: Dict[str, Dict[str, Any]] = {}  # insertion order = least recently seen first
_lock = threading.Lock()  # added on the server's loop, read on Anki's main thread


def _client_of(entry: Dict[str, Any]) -> Dict[str, str]:
    app = entry.get("app")
    if app and app not in (NO_KEY_LOCAL, NO_KEY_REMOTE):
        return {"id": "app:" + app, "label": app, "kind": "app"}
    if entry.get("origin"):
        return {"id": "origin:" + entry["origin"], "label": entry["origin"], "kind": "website"}
    label = NO_KEY_LOCAL if entry.get("local") else NO_KEY_REMOTE
    return {"id": "nokey:" + label, "label": label, "kind": "no_key"}


def failed(entry: Dict[str, Any]) -> bool:
    return (entry.get("status") or 0) >= 400 or bool(entry.get("error"))


def add(entry: Dict[str, Any]) -> None:
    """Record `entry` once its status is known; ms may still be filled in later."""
    who = _client_of(entry)
    entry["client"] = who["id"]
    with _lock:
        client = _clients.pop(who["id"], None)
        if client is None:
            client = {**who, "entries": deque(maxlen=PER_CLIENT), "requests": 0, "failed": 0,
                      "first": entry.get("time")}
            if who["kind"] != "app":
                keyless = [cid for cid, c in _clients.items() if c["kind"] != "app"]
                for cid in keyless[:max(0, len(keyless) - MAX_KEYLESS + 1)]:
                    del _clients[cid]
        _clients[who["id"]] = client  # now the most recently seen
        client["entries"].append(entry)
        client["requests"] += 1
        client["failed"] += failed(entry)
        client["last"] = entry.get("time")


def clients() -> List[Dict[str, Any]]:
    """Each client's totals since Anki started (or Clear), most recently seen first."""
    with _lock:
        return [{k: v for k, v in c.items() if k != "entries"} for c in reversed(_clients.values())]


def recent(client: Optional[str] = None, failed_only: bool = False, text: str = "") -> List[Dict[str, Any]]:
    """Copies of the matching entries, newest first, at most MAX_SHOWN."""
    with _lock:
        pools = [_clients[client]] if client in _clients else [] if client else list(_clients.values())
        entries = [e for c in pools for e in c["entries"]]
    needle = text.strip().lower()
    out = []
    for e in sorted(entries, key=lambda e: e.get("time") or 0, reverse=True):
        if failed_only and not failed(e):
            continue
        if needle and needle not in " ".join(str(e.get(k) or "") for k in (
                "method", "path", "action", "origin", "app", "error", "status")).lower():
            continue
        out.append(dict(e))
        if len(out) == MAX_SHOWN:
            break
    return out


def clear() -> None:
    with _lock:
        _clients.clear()
