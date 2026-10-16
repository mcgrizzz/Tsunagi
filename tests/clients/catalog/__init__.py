"""
The catalog (6.135): the requests the tested clients' code sends, one entry
for each option, outcome and kind of collection change, each compared whole
with AnkiConnect's answer at the pinned commit (reference.json, written by
tools/record_client_references.py).

standard.py holds what most clients send and the envelope matrix;
<client>.py the entries first sent by that client, named "... (Client)".
Entries hold all the data; a client's client.py only names what it sends.
"""
import importlib
from pathlib import Path

from clients.catalog.standard import ENVELOPE_KINDS, ENVELOPES, STANDARD

HERE = Path(__file__).parent
REFERENCE = HERE / "reference.json"
_ORIGINS = sorted(p.stem for p in HERE.glob("*.py") if p.stem not in ("__init__", "standard"))

ENTRIES = [
    *STANDARD,
    *(e for origin in _ORIGINS for e in importlib.import_module(f"clients.catalog.{origin}").ENTRIES),
    *ENVELOPES,
]

__all__ = ["ENTRIES", "ENVELOPE_KINDS", "REFERENCE"]
