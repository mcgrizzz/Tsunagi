"""
Record AnkiConnect's answers to the tested clients' cases (6.135,
tests/clients/support.py), from AnkiConnect at the pinned commit.

    python tools/record_client_references.py [CLIENT ...] [--checkout ~/refs/anki-connect]

Runs AnkiConnect's action code from the checkout (tools/upstream_reference.py
checks the commit), each case on a fresh collection seeded as the tests seed
the Shim's. Without a client name, every client is recorded.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.compat_bench.runtime import bootstrap, collection, endpoint  # noqa: E402

bootstrap()
from clients.support import (  # noqa: E402
    clients,
    reference_path,
    request_key,
    seed,
    send_case,
)

from tools.upstream_reference import UPSTREAM_REVISION  # noqa: E402


def record(name, module, checkout):
    cases = {}
    for c in module.CASES:
        with tempfile.TemporaryDirectory() as scratch, \
                collection(Path(scratch) / "collection.anki2") as col, \
                endpoint("upstream", checkout) as send:
            ctx = seed(col, Path(scratch))

            def post(method, body):
                response = send(method, "/", body, None)
                return response.status_code, response.content.decode("utf-8", errors="replace")

            cases[c.name] = {"request": request_key(c), "answer": send_case(post, col, c, ctx)}
    out = {"anki_connect": UPSTREAM_REVISION, "cases": cases}
    reference_path(name).write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                    encoding="utf-8")
    print(f"{name}: {len(cases)} cases")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("clients", nargs="*")
    parser.add_argument("--checkout", default=str(Path.home() / "refs/anki-connect"))
    args = parser.parse_args()
    found = clients()
    for name in args.clients or sorted(found):
        if name not in found:
            sys.exit(f"no client folder tests/clients/{name}")
        record(name, found[name], args.checkout)


if __name__ == "__main__":
    main()
