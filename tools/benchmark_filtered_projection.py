"""Compare eager/deferred filtered-card projections on a disposable collection.

Only the resource's expensive-group declaration changes between variants.
Requests run sequentially on one open fixture; each round reverses their order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.compat_bench.runtime import bootstrap, collection  # noqa: E402


def measure(size, repeats):
    from anki.cards import Card
    from fastapi.testclient import TestClient

    from tsunagi.app import app
    from tsunagi.http.v1.cards import caps

    groups = caps.expensive_groups
    with tempfile.TemporaryDirectory(prefix="tsunagi-filtered-projection-") as tmp:
        with collection(Path(tmp) / "collection.anki2") as col:
            model = col.models.by_name("Basic")
            for i in range(size):
                note = col.new_note(model)
                note["Front"] = f"projection-{i}"
                note["Back"] = "benchmark"
                col.add_note(note, 1)
            ids = sorted(int(cid) for cid in col.find_cards(""))
            assert len(ids) == size
            expected = ids[::100]
            col.sched.suspend_cards(expected)
            cases = []
            with TestClient(app, base_url="http://127.0.0.1") as client:
                for select in ("id,question", "id,queue"):
                    variants = {name: {"samples_ms": []} for name in ("eager", "deferred")}
                    reference = None

                    def request(select=select):
                        response = client.get("/v1/cards", params={
                            "select": select, "where": "queue==-1",
                        })
                        response.raise_for_status()
                        page = response.json()
                        assert page["next_cursor"] is None
                        assert [row["id"] for row in page["items"]] == expected
                        return page["items"]

                    try:
                        for trial in range(repeats + 1):
                            order = ("eager", "deferred") if trial % 2 == 0 else ("deferred", "eager")
                            for name in order:
                                caps.expensive_groups = () if name == "eager" else groups
                                start = time.perf_counter()
                                items = request()
                                elapsed = (time.perf_counter() - start) * 1000
                                if reference is None:
                                    reference = items
                                assert items == reference
                                if trial == 0:
                                    variants[name]["first_ms"] = elapsed
                                else:
                                    variants[name]["samples_ms"].append(elapsed)

                        for name, result in variants.items():
                            caps.expensive_groups = () if name == "eager" else groups
                            rendered = []
                            original = Card.question

                            def question(card, *args, _rendered=rendered, _original=original, **kwargs):
                                _rendered.append(int(card.id))
                                return _original(card, *args, **kwargs)

                            # Instrument a separate request, outside the timed samples.
                            with patch.object(Card, "question", question):
                                assert request() == reference
                            required = ([] if select == "id,queue" else
                                        ids if name == "eager" else expected)
                            assert rendered == required
                            result["question_calls"] = len(rendered)
                            result["median_ms"] = statistics.median(result["samples_ms"])
                    finally:
                        caps.expensive_groups = groups
                    cases.append({"cards": size, "matches": len(expected), "select": select,
                                  "variants": variants, "equal_results": True})
                    print(size, select, {name: round(v["median_ms"], 2)
                                         for name, v in variants.items()}, flush=True)
            return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 10000])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or any(size < 1 for size in args.sizes):
        parser.error("sizes and repeats must be positive")
    bootstrap()
    from tsunagi.adapters.config import DEFAULTS
    from tsunagi.adapters.settings import settings

    settings.configure(dict(DEFAULTS), persist=None)
    files = ["tsunagi/http/middleware.py", "tsunagi/shared/route_factory.py",
             "tsunagi/shared/planning.py", "tsunagi/http/v1/cards.py",
             "tools/benchmark_filtered_projection.py"]
    report = {
        "python": sys.version, "anki": version("anki"), "repeats": args.repeats,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=ROOT)),
        "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in files},
        "limits": "Headless HTTP client; fake Qt dispatch; sequential reads on one open collection; no socket.",
        "cases": [case for size in args.sizes for case in measure(size, args.repeats)],
        "completed": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
