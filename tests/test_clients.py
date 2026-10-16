"""
Tested AnkiConnect clients (6.135, tests/clients/support.py): the catalog's
entries answered by the Shim as AnkiConnect answers them
(tests/clients/catalog/reference.json), and each client's declaration
checked against the catalog.
"""
import json
import re
from collections import Counter, defaultdict

import pytest
from clients.catalog import ENTRIES, ENVELOPE_KINDS, REFERENCE
from clients.support import (
    MISSING,
    clients,
    mask,
    pick,
    request_hash,
    requests,
    seed,
    send_case,
    shape_key,
    view,
)

CLIENTS = clients()
REQUIRED = {"name", "repo", "commit", "read", "files"}
RECORDED = json.loads(REFERENCE.read_text(encoding="utf-8"))["cases"] if REFERENCE.is_file() else {}


@pytest.mark.parametrize("c", ENTRIES, ids=lambda c: c.name)
def test_entry(client, col, tmp_path, c):
    recorded = RECORDED.get(c.name)
    assert recorded is not None, "no reference: python tools/record_client_references.py"
    assert recorded["request"] == request_hash(c), (
        "the entry changed since its reference: python tools/record_client_references.py")
    ctx = seed(col, tmp_path)

    def send(method, body):
        response = client.request(method, "/", content=body,
                                  headers={"Content-Type": "application/json"})
        return response.status_code, response.text

    expected = view(c, recorded["answer"])
    if c.differs is not None:
        why, shim = c.differs
        declared = {read: mask(value) for read, value in shim.items()}
        assert all(expected.get(read) != value for read, value in declared.items()), (
            f"declared different but AnkiConnect answers the same: {why}")
        expected.update(declared)
    assert view(c, send_case(send, col, c, ctx)) == expected


def test_catalog_is_complete():
    names = Counter(c.name for c in ENTRIES)
    assert not [n for n, k in names.items() if k > 1], "entry names must be unique"
    stale = set(RECORDED) - set(names)
    assert not stale, f"references for removed entries: {sorted(stale)}"


EXERCISED = defaultdict(set)   # action -> the shape of every request some entry sends to it
ANSWERS = defaultdict(list)    # action -> the recorded answers of entries that send it
for _c in ENTRIES:
    for _action, _params in requests(_c):
        EXERCISED[_action].add(shape_key(_action, _params))
    _first = next(requests(_c))[0]
    if _c.name in RECORDED:
        _body = RECORDED[_c.name]["answer"]["body"]
        # Versions below 6 answer the bare result.
        ANSWERS[_first].append(_body if isinstance(_body, dict) and {"result", "error"} <= set(_body)
                               else {"result": _body, "error": None})


def _norm(path):
    return re.sub(r"\[[0-9*]+\]", "[*]", path.partition("~")[0].rstrip("?"))


def _overlap(read, path):
    """Whether a read sees what a path names: one is the other or inside it."""
    a, b = _norm(read), _norm(path)
    return not a or not b or a == b or a.startswith((b + ".", b + "[")) or b.startswith((a + ".", a + "["))


def _reads(module, action):
    """What the client reads of an action's answers: also all of it when it batches the action and reads multi."""
    reads = list(module.SENDS[action][1])
    shapes, multi_reads = module.SENDS.get("multi", ([], ()))
    batched = {a.get("action") for s in shapes for a in s.get("actions", ()) if isinstance(a, dict)}
    if multi_reads and action in batched:
        reads.append("")
    return reads


@pytest.mark.parametrize("name", sorted(CLIENTS))
def test_client(name):
    module = CLIENTS[name]
    assert REQUIRED <= set(module.CLIENT), f"CLIENT needs {sorted(REQUIRED - set(module.CLIENT))}"
    for kind, value in module.ENVELOPE.items():
        assert value in ENVELOPE_KINDS.get(kind, ()), f"ENVELOPE {kind}={value!r} isn't one the matrix covers"
    for action, (shapes, reads) in module.SENDS.items():
        for shape in shapes:
            assert shape_key(action, shape) in EXERCISED[action], (
                f"{action}: no catalog entry sends a request of this shape, add one: {shape}")
        for read in (r for r in reads if not r.endswith("?")):  # "?": may be absent
            seen = [v for body in ANSWERS[action] for v in pick(body, read).values()]
            assert any(v is not MISSING and v != "<missing>" for v in seen), (
                f"{action}: no recorded answer has {read!r}")
    accepts = getattr(module, "ACCEPTS", {})
    differing = {c.name: c for c in ENTRIES if c.differs is not None}
    assert set(accepts) <= set(differing), f"ACCEPTS names no deliberate difference: {sorted(set(accepts) - set(differing))}"
    for c in differing.values():
        action, params = next(requests(c))
        if action not in module.SENDS or shape_key(action, params) not in {
                shape_key(action, s) for s in module.SENDS[action][0]}:
            continue
        seen = [r for r in _reads(module, action) for path in c.differs[1] if _overlap(r, path)]
        assert not seen or c.name in accepts, (
            f"{c.name} differs from AnkiConnect deliberately ({c.differs[0]}) and {module.CLIENT['name']} "
            f"reads it ({seen}): check the client, then accept it in ACCEPTS")


def test_compatible_clients_page_is_current():
    from tools.compatible_clients import PAGE, render

    assert PAGE.read_text(encoding="utf-8") == render(), "out of date: python tools/compatible_clients.py"
