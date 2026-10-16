"""
The standard requests and envelopes (tests/clients/catalog.py), run once: a
client's cases.py lists the ones its code sends (USES) instead of repeating them.
"""
from clients.catalog import ENVELOPES, STANDARD

CLIENT = {
    "name": "Standard requests and envelopes",
    "repo": "tests/clients/catalog.py",
    "commit": "de6e6e1",
    "read": "2026-10-15",
    "files": ["tests/clients/catalog.py"],
    "notes": "Not a client: what most clients send, taken from the tested clients' cases.",
}

CASES = STANDARD + ENVELOPES
