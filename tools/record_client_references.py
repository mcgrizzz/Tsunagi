"""
Record AnkiConnect's answers to the catalog's entries (6.135,
tests/clients/support.py), from AnkiConnect at the pinned commit, into
tests/clients/catalog/reference.json.

    python tools/record_client_references.py [--checkout ~/refs/anki-connect]

Runs AnkiConnect's action code from the checkout (tools/upstream_reference.py
checks the commit), each entry on a fresh collection seeded as the tests seed
the Shim's.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.compat_bench.runtime import bootstrap, collection, endpoint  # noqa: E402

bootstrap()
from clients.catalog import ENTRIES, REFERENCE  # noqa: E402
from clients.support import request_hash, seed, send_case  # noqa: E402

from tools.upstream_reference import UPSTREAM_REVISION  # noqa: E402


def record(checkout):
    cases = {}
    for c in ENTRIES:
        with tempfile.TemporaryDirectory() as scratch, \
                collection(Path(scratch) / "collection.anki2") as col, \
                endpoint("upstream", checkout) as send:
            ctx = seed(col, Path(scratch))

            def post(method, body, headers):
                response = send(method, "/", body, None, headers)
                return response.status_code, response.content.decode("utf-8", errors="replace")

            cases[c.name] = {"request": request_hash(c), "answer": send_case(post, col, c, ctx)}
    # One case per line: a re-recorded case is a one-line diff.
    lines = [f"  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)}"
             for k, v in sorted(cases.items())]
    REFERENCE.write_text(
        f'{{\n "anki_connect": "{UPSTREAM_REVISION}",\n "cases": {{\n' + ",\n".join(lines) + "\n }\n}\n",
        encoding="utf-8")
    print(f"{len(cases)} entries")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--checkout", default=str(Path.home() / "refs/anki-connect"))
    record(parser.parse_args().checkout)


if __name__ == "__main__":
    main()
