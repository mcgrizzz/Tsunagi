"""
Tested AnkiConnect clients (6.135, tests/clients/support.py): each request a
client's code sends gets, in what that client reads, the answer AnkiConnect
gives at the pinned commit (tests/clients/<name>/reference.json).
"""
import json

import pytest
from clients.catalog import ENVELOPE_KINDS, STANDARD_NAMES
from clients.support import (
    clients,
    mask,
    reference_path,
    request_key,
    seed,
    send_case,
    view,
)

CLIENTS = clients()
REQUIRED = {"name", "repo", "commit", "read", "files"}


def _reference(name):
    path = reference_path(name)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"cases": {}}


CASES = [pytest.param(name, c, id=f"{name}: {c.name}")
         for name, module in CLIENTS.items() for c in module.CASES]


@pytest.mark.parametrize("name,c", CASES)
def test_client_case(client, col, tmp_path, name, c):
    recorded = _reference(name)["cases"].get(c.name)
    assert recorded is not None, f"no reference: python tools/record_client_references.py {name}"
    assert recorded["request"] == request_key(c), (
        f"the case changed since its reference: python tools/record_client_references.py {name}")
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


@pytest.mark.parametrize("name", sorted(CLIENTS))
def test_client_folder_is_complete(name):
    module = CLIENTS[name]
    assert REQUIRED <= set(module.CLIENT), f"CLIENT needs {sorted(REQUIRED - set(module.CLIENT))}"
    names = [c.name for c in module.CASES]
    assert len(names) == len(set(names)), "case names must be unique"
    stale = set(_reference(name)["cases"]) - set(names)
    assert not stale, f"reference answers for removed cases: {sorted(stale)}"
    # The checklist: standard requests this client sends, run once in standard/.
    unknown = set(getattr(module, "USES", ())) - STANDARD_NAMES
    assert not unknown, f"USES names no standard request: {sorted(unknown)}"
    for kind, value in getattr(module, "ENVELOPE", {}).items():
        assert value in ENVELOPE_KINDS.get(kind, ()), f"ENVELOPE {kind}={value!r} isn't one the matrix covers"
