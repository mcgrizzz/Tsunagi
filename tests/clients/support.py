"""
Tested AnkiConnect clients (6.135): the requests each client's code sends,
answered by the Shim as AnkiConnect answers them.

Two parts:

- tests/clients/catalog/: the entries, each a request with its data and the
  collection state it needs (Case, below). Each is compared whole with
  AnkiConnect's answer at the pinned commit (tools/upstream_reference.py),
  recorded in catalog/reference.json by tools/record_client_references.py:
  one entry per line, a hash of the request, the answer, and for effects
  what the request changed in the collection. Recorded on Linux: behaviour
  that depends on the OS (a backslash in a path) isn't covered.
- tests/clients/<name>/client.py, one per client, no data: CLIENT (its repo,
  the commit read, the files that talk to AnkiConnect), ENVELOPE, SENDS
  (each action its code sends: its requests' shape and what it reads of the
  answer) and ACCEPTS (deliberate differences it would see, accepted).
  Written from reading the client's source; its code is never run.

tests/test_clients.py runs the entries against the Shim, then checks each
client against the catalog: every option it sends is exercised by an entry,
what it reads is in a recorded answer, and a deliberate difference on what
it reads fails until the client accepts it.

Adding a client, cheapest first:

1. Clone it into an empty scratch folder (its code is only read).
   tools/scan_client.py CHECKOUT --save NAME lists the actions it names and
   where (sites.json, with a hash per call site), and its envelope hints.
2. client.py: CLIENT (commit and date checked), ENVELOPE and SENDS, from
   reading only the call sites the scan lists.
3. The tests name any option no entry exercises: add an entry for it,
   usually to catalog/<name>.py, then tools/record_client_references.py.
   tools/scan_client.py --coverage NAME names actions SENDS leaves out.

A checked client is rechecked only when the owner asks; tools/scan_client.py
CHECKOUT --compare NAME reports which call sites changed since.
"""
import base64
import hashlib
import importlib.util
import json
import re
import threading
from collections import Counter
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

HERE = Path(__file__).parent
PNG = b"\x89PNG\r\n\x1a\nfake"
B64 = base64.b64encode(PNG).decode()
MD5 = hashlib.md5(PNG).hexdigest()
MISSING = "<missing>"


@dataclass(frozen=True)
class Case:
    name: str
    body: Callable[[Dict[str, Any]], Any]
    # What the client reads: paths into the answer. "" is the whole answer,
    # "result.permission" a key, "result[*].noteId" a key of every item,
    # "result[0]" one item, "result.*.total_in_deck" a key of every value of
    # an object. A suffix compares less: "~type" its JSON type (a time, a
    # count that varies), "~keys" an object's keys (exactly these),
    # "~present" only that it's there.
    reads: Tuple[str, ...]
    # Also compare what the request changed in the collection: notes, cards'
    # scheduling, decks, note types, tags and media files.
    effects: bool = False
    method: str = "POST"
    # Changes to the seeded collection this case needs first: setup(col, ctx).
    # It may return more ids for the body ({"nid2": ...}); ctx["cleanup"]
    # collects what to undo afterwards (serve() adds to it).
    setup: Optional[Callable[[Any, Dict[str, Any]], Optional[Dict[str, Any]]]] = None
    # Requests sent after this one, each with ctx["answer"], the answer
    # before it (a read back after a write, or a request built from an answer).
    then: Tuple["Case", ...] = ()
    # A deliberate difference from AnkiConnect at the pin: (why, {read: the
    # Shim's value}). Those reads are expected to answer that instead.
    differs: Optional[Tuple[str, Dict[str, Any]]] = None
    # Request headers other than Content-Type: application/json, as
    # ((name, value), ...); a value of None leaves that header out.
    headers: Tuple[Tuple[str, Optional[str]], ...] = ()


def case(name, action, params=None, *, version=6, reads=("result", "error"),
         effects=False, method="POST", setup=None, then=(), differs=None, headers=(), **extra):
    """A request built from the seeded collection's ids (ctx), when params is a function."""
    def body(ctx):
        out = {"action": action, "version": version, **extra}
        if params is not None:
            out["params"] = params(ctx) if callable(params) else params
        return out
    return Case(name, body, tuple(reads), effects, method, setup, tuple(then), differs, tuple(headers))


def named(origin, cases):
    """A client's catalog entries, each name ending in the client's: "addNote (Memento)"."""
    return [replace(c, name=f"{c.name} ({origin})") for c in cases]


def raw(name, body, *, reads=("",), effects=False, method="POST", setup=None, then=(), differs=None, headers=()):
    """A request body sent as it is (a function of ctx), for envelopes case() can't build.
    A body of bytes is sent unencoded (a body that isn't JSON)."""
    return Case(name, body, tuple(reads), effects, method, setup, tuple(then), differs, tuple(headers))


def note(**over):
    out = {"deckName": "Default", "modelName": "Basic",
           "fields": {"Front": "犬", "Back": "dog"}, "tags": ["t"]}
    out.update(over)
    return out


def seed(col, scratch: Path) -> Dict[str, Any]:
    """The collection every case starts from; returns the ids cases refer to."""
    n = col.new_note(col.models.by_name("Basic"))
    n["Front"], n["Back"] = "犬", "dog"
    n.tags = ["seeded"]
    col.add_note(n, 1)
    col.media.write_data("seed-1.txt", b"s")
    path = scratch / "local.png"
    path.write_bytes(PNG)
    return {"nid": n.id, "cid": col.card_ids_of_note(n.id)[0], "png_path": str(path),
            "cleanup": []}


def serve(ctx, respond: Callable[[str], Tuple[int, bytes]]) -> str:
    """
    A local HTTP server for media URLs, for this case only: respond(path)
    gives (status, body) for each GET. Returns its base URL.
    """
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = respond(self.path)
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def stop():
        server.shutdown()
        server.server_close()

    ctx["cleanup"].append(stop)
    return f"http://127.0.0.1:{server.server_address[1]}"


class _Token(str):
    """A placeholder for an id or answer in the recorded request; indexing names a part of it."""
    def __getitem__(self, key):
        return _Token(f"{self}[{key}]")


class _Placeholders(dict):
    def __missing__(self, key):
        return _Token(f"<{key}>")


def _readable(body):
    return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body


def request_key(c: Case) -> str:
    """The request with placeholder ids: a reference recorded for another request is stale."""
    ctx = _Placeholders(cleanup=[])
    requests = [{"method": step.method, "body": _readable(step.body(ctx)),
                 **({"headers": [list(h) for h in step.headers]} if step.headers else {})}
                for step in (c, *c.then)]
    return json.dumps(requests if c.then else requests[0], ensure_ascii=False, sort_keys=True)


def request_hash(c: Case) -> str:
    """What reference.json keeps of the request: enough to tell it changed."""
    return hashlib.sha256(request_key(c).encode()).hexdigest()[:16]


def _state(col) -> Dict[str, Any]:
    notes = sorted([list(col.get_note(n).fields), sorted(col.get_note(n).tags)]
                   for n in col.find_notes(""))
    cards = sorted([card.note().fields[0], card.ord, card.queue, card.type, card.ivl,
                    card.factor, card.reps, card.lapses]
                   for card in map(col.get_card, col.find_cards("")))
    models = sorted([m["name"], [f["name"] for f in m["flds"]], [t["name"] for t in m["tmpls"]]]
                    for m in col.models.all())
    return {
        "notes": notes,
        "cards": cards,
        "decks": sorted(d.name for d in col.decks.all_names_and_ids()),
        "models": models,
        "tags": sorted(col.tags.all()),
        "media": sorted(p.name for p in Path(col.media.dir()).iterdir() if p.is_file()),
    }


def _changes(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Each part of the collection that changed: its items added and removed (a card rescheduled is both)."""
    out = {}
    for part in after:
        old = Counter(json.dumps(item, ensure_ascii=False) for item in before[part])
        new = Counter(json.dumps(item, ensure_ascii=False) for item in after[part])
        change = {"added": sorted((new - old).elements()), "removed": sorted((old - new).elements())}
        change = {k: [json.loads(item) for item in v] for k, v in change.items() if v}
        if change:
            out[part] = change
    return out


def _send_one(send, c: Case, ctx) -> Dict[str, Any]:
    body = c.body(ctx)
    content = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
    status, text = send(c.method, content, dict(c.headers))
    try:
        body = json.loads(text)
    except ValueError:
        body = {"<not json>": text[:200]}
    return {"status": status, "body": body}


def request_headers(extra) -> Dict[str, str]:
    """Content-Type: application/json unless a case's headers say otherwise; None leaves a header out."""
    out = {"Content-Type": "application/json"}
    for name, value in (extra or {}).items():
        out = {k: v for k, v in out.items() if k.lower() != name.lower()}
        if value is not None:
            out[name] = value
    return out


def send_case(send, col, c: Case, ctx) -> Dict[str, Any]:
    """Send the case with send(method, body_bytes, headers) -> (status, text); the answers and the effects."""
    try:
        if c.setup is not None:
            more = c.setup(col, ctx)
            if isinstance(more, dict):  # a lambda's last call may return anything else
                ctx.update(more)
        before = _state(col) if c.effects else None
        out = _send_one(send, c, ctx)
        if c.then:
            out["then"] = []
            answer = out["body"]
            for step in c.then:
                ctx["answer"] = answer
                got = _send_one(send, step, ctx)
                out["then"].append(got)
                answer = got["body"]
        if c.effects:
            out["effects"] = _changes(before, _state(col))
        return out
    finally:
        for undo in ctx.get("cleanup", []):
            undo()


# ----- Shapes: what a client sends, without its data -----
# A client's SENDS lists each distinct request it sends to an action as a
# shape, matched exactly by some catalog entry: the same keys present and
# absent. In a shape, str, int and float stand for any such value, PATH for
# a filename with a folder in it, "" for an empty string; True, False, None
# and the strings that choose a behaviour (CHOICES) are themselves. A list
# holds its items' distinct shapes ([] when empty). The keys of a note's
# fields or templates are its note type's names: {str: v}, with a tuple of
# the values' distinct shapes when they differ ((str, "")). multi's shape is
# the actions it batches, without their params, which are their own action's.

PATH = "<path>"
CHOICES = {"duplicateScope"}
# The note most clients send, as a shape: {**NOTE, "options": {...}} adds to it.
NOTE = {"deckName": str, "fields": {str: str}, "modelName": str, "tags": [str]}
_NAMED_KEYS = {"fields", "templates"}
_PLACEHOLDER = re.compile(r"<([a-z0-9_]+)>(\[[^\]]*\])*")


def _distinct(values):
    return sorted({json.dumps(v, sort_keys=True) for v in values})


def _canon(value, key=None):
    """A request's or a shape's canonical form: data replaced by its kind."""
    if isinstance(value, dict):
        if key in _NAMED_KEYS and value:
            values = [w for v in value.values() for w in (v if isinstance(v, tuple) else (v,))]
            return {"*": _distinct(_canon(v) for v in values)}
        return {k: _canon(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return _distinct(_canon(v, key) for v in value) or "[]"
    if value is str:
        return "<text>"
    if value is int or value is float or (not isinstance(value, bool) and isinstance(value, (int, float))):
        return "<number>"
    if isinstance(value, str):
        if key == "action" or key in CHOICES or value == PATH:
            return value
        if value == "":
            return "<empty>"
        placeholder = _PLACEHOLDER.fullmatch(value)
        if placeholder and ("id" in placeholder[1] or placeholder[1] == "answer"):
            return "<number>"  # an entry's placeholder for an id (request_key)
        if placeholder and placeholder[1] == "cards":
            # A setup's list of card ids (the card-state matrix), or one of them.
            return "<number>" if placeholder[2] else _distinct(["<number>"])
        if key == "filename" and ("/" in value or "\\" in value):
            return PATH
        return "<text>"
    return value  # True, False, None


def shape_key(action, params) -> str:
    """What two requests to an action must share to count as the same request."""
    if action == "multi" and isinstance(params, dict) and isinstance(params.get("actions"), list):
        params = {**params, "actions": [{k: v for k, v in a.items() if k != "params"} if isinstance(a, dict) else a
                                        for a in params["actions"]]}
    return json.dumps(_canon(params), sort_keys=True)


def requests(c: Case):
    """(action, params) of each request a case sends: its steps, and the actions a multi batches."""
    def walk(body):
        if not isinstance(body, dict):  # a body that isn't JSON (raw bytes)
            yield None, {}
            return
        yield body.get("action"), body.get("params", {})
        params = body.get("params")
        actions = params.get("actions") if isinstance(params, dict) else None
        if body.get("action") == "multi" and isinstance(actions, list):
            for inner in actions:
                if isinstance(inner, dict):
                    yield from walk(inner)

    for step in (c, *c.then):
        key = json.loads(request_key(step))
        yield from walk(key["body"] if "body" in key else key[0]["body"])


def _segments(path: str):
    return [s for s in re.split(r"\.|(\[\*\]|\[[0-9]+\])", path) if s]


def pick(value, path: str) -> Dict[str, Any]:
    """Each concrete path the read reaches, and its value (or what the suffix compares)."""
    out: Dict[str, Any] = {}
    path, _, compare = path.partition("~")

    def leaf(at, v):
        if compare == "type":
            v = "<missing>" if v is MISSING else type(v).__name__
        elif compare == "keys":
            v = sorted(v) if isinstance(v, dict) else type(v).__name__
        elif compare == "present":
            v = "<missing>" if v is MISSING else "<present>"
        out[at] = v

    def walk(v, segs, at):
        if not segs:
            leaf(at, v)
            return
        seg, rest = segs[0], segs[1:]
        if seg == "[*]":
            if isinstance(v, list):
                for i, item in enumerate(v):
                    walk(item, rest, f"{at}[{i}]")
            else:
                leaf(at, v)
        elif seg.startswith("["):
            i = int(seg[1:-1])
            if isinstance(v, list) and i < len(v):
                walk(v[i], rest, f"{at}{seg}")
            else:
                leaf(f"{at}{seg}", MISSING)
        elif seg == "*":
            if isinstance(v, dict):
                for k in sorted(v):
                    walk(v[k], rest, f"{at}.{k}")
            else:
                leaf(at, v)
        elif isinstance(v, dict) and seg in v:
            walk(v[seg], rest, f"{at}.{seg}" if at else seg)
        else:
            leaf(f"{at}.{seg}" if at else seg, MISSING)

    walk(value, _segments(path), "")
    return out


_MASKS = [
    (re.compile(r"\b1[0-9]{12}\b"), "<id>"),                     # note, card, deck and model ids
    (re.compile(r'"(mod|usn)": -?[0-9]+'), r'"\1": <t>'),       # modification times
    (re.compile(r'"id": -?[0-9]{15,20}'), '"id": <fid>'),       # field and template ids
    (re.compile(r"\b(127\.0\.0\.1|localhost):[0-9]+"), r"\1:<port>"),  # serve()'s port
    # Anki fuzzes the intervals cardsInfo previews, seeded by the card's id.
    (re.compile(r'"nextReviews": \[[^\]]*\]'), '"nextReviews": <fuzzed>'),
    # getMediaDirPath: each run's collection is in its own scratch folder.
    (re.compile(r'"[^"]*collection\.media"'), '"<media folder>"'),
    # getCollectionStatsHTML's footer: "Generated on Fri Oct 16 13:04:03 2026".
    (re.compile(r"Generated on [A-Z][a-z]{2} [A-Z][a-z]{2} +[0-9]+ [0-9:]{8} [0-9]{4}"), "Generated on <time>"),
]


def _masked(text: str) -> str:
    for pattern, repl in _MASKS:
        text = pattern.sub(repl, text)
    return text


def mask(value) -> str:
    return _masked(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _view_of(c: Case, answer: Dict[str, Any], prefix: str, out: Dict[str, str]):
    out[f"{prefix}status"] = str(answer["status"])
    for read in c.reads:
        for at, v in pick(answer["body"], read).items():
            # Object keys in the path can be ids (getDeckStats by deck id).
            out[prefix + _masked(at or "<answer>")] = mask(v)


def view(c: Case, answer: Dict[str, Any]) -> Dict[str, str]:
    """What the client sees of the answers: each status and read, and the effects if asked."""
    out: Dict[str, str] = {}
    _view_of(c, answer, "", out)
    for i, (step, got) in enumerate(zip(c.then, answer.get("then", [])), 1):
        _view_of(step, got, f"then {i}: ", out)
    if c.effects:
        out["effects"] = mask(answer["effects"])
    return out


def clients() -> Dict[str, Any]:
    """Each client folder's client module, by folder name."""
    out = {}
    for path in sorted(HERE.glob("*/client.py")):
        spec = importlib.util.spec_from_file_location(f"client_{path.parent.name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out[path.parent.name] = module
    return out

