"""
Tested AnkiConnect clients (6.135): the requests each client's code sends,
answered by the Shim as AnkiConnect answers them.

One folder per client, tests/clients/<name>/:

- cases.py: CLIENT (its repo, the commit read and the files that talk to
  AnkiConnect) and CASES, the requests that code sends. Each case names what
  the client reads from the answer, so only that is compared. Written from
  reading the client's source; its code is never run.
- reference.json: AnkiConnect's answers to the same cases at the pinned
  commit (tools/upstream_reference.py), written by
  tools/record_client_references.py. Recorded on Linux: behaviour that
  depends on the OS (a backslash in a path) isn't covered.

tests/test_clients.py sends every case to the Shim, on a collection seeded
the same way, and compares what the client reads with the reference.

Adding a client, cheapest first:

1. Clone it into an empty scratch folder (its code is only read).
   tools/scan_client.py CHECKOUT --save NAME lists the actions it names and
   where (sites.json, with a hash per call site), and its envelope hints.
2. cases.py: CLIENT (commit and date checked), ENVELOPE, USES (the standard
   requests of catalog.py its code sends; they run once, in standard/), and
   CASES only for what is its own: other option shapes, queries, one-offs.
   Read only the call sites the scan lists.
3. tools/record_client_references.py NAME, then the tests.
   tools/scan_client.py --coverage NAME names actions no case covers yet.

A checked client is rechecked only when the owner asks; tools/scan_client.py
CHECKOUT --compare NAME reports which call sites changed since.
"""
import base64
import hashlib
import importlib.util
import json
import re
import threading
from dataclasses import dataclass
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
    # Also compare the collection afterwards: notes, cards' scheduling, decks,
    # note types, tags and media files.
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


def case(name, action, params=None, *, version=6, reads=("result", "error"),
         effects=False, method="POST", setup=None, then=(), differs=None, **extra):
    """A request built from the seeded collection's ids (ctx), when params is a function."""
    def body(ctx):
        out = {"action": action, "version": version, **extra}
        if params is not None:
            out["params"] = params(ctx) if callable(params) else params
        return out
    return Case(name, body, tuple(reads), effects, method, setup, tuple(then), differs)


def raw(name, body, *, reads=("",), effects=False, method="POST", setup=None, then=(), differs=None):
    """A request body sent as it is (a function of ctx), for envelopes case() can't build."""
    return Case(name, body, tuple(reads), effects, method, setup, tuple(then), differs)


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


def request_key(c: Case) -> str:
    """The request with placeholder ids: a reference recorded for another request is stale."""
    ctx = _Placeholders(cleanup=[])
    requests = [{"method": step.method, "body": step.body(ctx)} for step in (c, *c.then)]
    return json.dumps(requests if c.then else requests[0], ensure_ascii=False, sort_keys=True)


def _effects(col) -> Dict[str, Any]:
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


def _send_one(send, c: Case, ctx) -> Dict[str, Any]:
    status, text = send(c.method, json.dumps(c.body(ctx), ensure_ascii=False).encode())
    try:
        body = json.loads(text)
    except ValueError:
        body = {"<not json>": text[:200]}
    return {"status": status, "body": body}


def send_case(send, col, c: Case, ctx) -> Dict[str, Any]:
    """Send the case with send(method, body_bytes) -> (status, text); the answers and the effects."""
    try:
        if c.setup is not None:
            more = c.setup(col, ctx)
            if isinstance(more, dict):  # a lambda's last call may return anything else
                ctx.update(more)
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
            out["effects"] = _effects(col)
        return out
    finally:
        for undo in ctx.get("cleanup", []):
            undo()


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
    """Each client folder's cases module, by folder name."""
    out = {}
    for path in sorted(HERE.glob("*/cases.py")):
        spec = importlib.util.spec_from_file_location(f"client_cases_{path.parent.name}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out[path.parent.name] = module
    return out


def reference_path(name: str) -> Path:
    return HERE / name / "reference.json"
