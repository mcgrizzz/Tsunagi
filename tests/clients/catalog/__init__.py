"""
The catalog (6.135): the requests the tested clients' code sends, one entry
for each option, outcome and kind of collection change, each compared whole
with AnkiConnect's answer at the pinned commit (reference.json, written by
tools/record_client_references.py).

standard.py holds what most clients send, the card-state matrix and the
envelope matrix; <client>.py the entries first sent by that client, named
"... (Client)". Entries hold all the data; a client's client.py only names
what it sends. A client whose envelope isn't version 6 POST without a key
also gets each entry it sends in its own envelope ("... [Yomitan's envelope]").
"""
import importlib
from dataclasses import replace
from pathlib import Path

from clients.catalog.standard import ENVELOPE_KINDS, ENVELOPES, STANDARD, STATES
from clients.support import clients, request_key, requests, shape_key

HERE = Path(__file__).parent
REFERENCE = HERE / "reference.json"
_ORIGINS = sorted(p.stem for p in HERE.glob("*.py") if p.stem not in ("__init__", "standard"))

_OWN = [
    *STANDARD,
    *STATES,
    *(e for origin in _ORIGINS for e in importlib.import_module(f"clients.catalog.{origin}").ENTRIES),
]


def _in_envelope(c, envelope):
    """The entry as a client with this envelope sends it, its whole answer compared."""
    def wrap(body_of):
        def body(ctx):
            out = dict(body_of(ctx))
            if envelope["version"] == "absent":
                out.pop("version", None)
            else:
                out["version"] = envelope["version"]
            if envelope["key"] == "null":
                out["key"] = None
            if envelope["params"] == "omit-when-empty" and out.get("params") == {}:
                out.pop("params")
            return out
        return body

    return replace(c, body=wrap(c.body), method=envelope["method"], reads=("",),
                   then=tuple(replace(s, body=wrap(s.body), method=envelope["method"], reads=("",))
                              for s in c.then))


def _envelope_entries():
    out, seen = [], {request_key(c) for c in _OWN}
    for module in clients().values():
        envelope = module.ENVELOPE
        if (envelope["version"], envelope["method"], envelope["key"]) == (6, "POST", "absent"):
            continue
        for action, (shapes, _reads) in module.SENDS.items():
            for shape in shapes:
                wanted = shape_key(action, shape)
                entry = next(c for c in _OWN if any(a == action and shape_key(a, p) == wanted
                                                   for a, p in [next(requests(c))]))
                variant = replace(_in_envelope(entry, envelope),
                                  name=f"{entry.name} [{module.CLIENT['name']}'s envelope]")
                if request_key(variant) not in seen:
                    seen.add(request_key(variant))
                    out.append(variant)
    return out


ENTRIES = [*_OWN, *ENVELOPES, *_envelope_entries()]

__all__ = ["ENTRIES", "ENVELOPE_KINDS", "REFERENCE"]
