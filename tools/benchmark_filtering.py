"""Compare native note filtering with a previous shared-filter implementation.

Uses disposable real Anki collections and the existing headless HTTP harness.
Workers run sequentially; only the filtering module changes between variants.
"""
from __future__ import annotations

import argparse
import builtins
import hashlib
import importlib.util
import json
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.compat_bench.runtime import (  # noqa: E402
    Requests,
    bootstrap,
    collection,
    endpoint,
)


def run_worker(config):
    bootstrap()
    from tsunagi.shared import filtering, route_factory

    if config["variant"] == "baseline":
        # Relative imports and dataclass registration need a package/module name.
        name = "tsunagi.shared._benchmark_filtering_baseline"
        spec = importlib.util.spec_from_loader(name, loader=None)
        filtering = importlib.util.module_from_spec(spec)
        sys.modules[name] = filtering
        source = Path(config["baseline_file"]).read_text()
        exec(compile(source, config["baseline_file"], "exec"), filtering.__dict__)
        route_factory.build_predicate = filtering.build_predicate

    allowed = config["allowed"]
    control = allowed == 0
    query = ("tags[] == tag0" if control else
             "tags[] in " + json.dumps([f"tag{i}" for i in range(allowed)]))
    params = {"select": "id", "shape": "object", "where": [query]}
    expected = sorted(nid for nid, tag in config["notes"] if tag < max(1, allowed))
    samples = []

    with tempfile.TemporaryDirectory(prefix="tsunagi-filter-worker-") as scratch:
        profile = Path(scratch) / "profile"
        shutil.copytree(config["seed"], profile)
        with collection(profile / "collection.anki2") as col, endpoint("native", None) as send:
            def request(method="GET"):
                client = Requests(send)
                body = client.native(method, "/v1/notes" if method == "GET" else "/v1/notes/query", params)
                assert body["next_cursor"] is None
                ids = [item["id"] for item in body["items"]]
                assert sorted(ids) == expected
                return client.actions[0]

            for _ in range(config["repeats"] + 1):
                samples.append(request())
            # GET/POST parity and instrumentation are outside the timed trials.
            request("POST")
            builds = []

            def counted_set(values):
                builds.append(1)
                return builtins.set(values)

            filtering.set = counted_set
            try:
                request()
            finally:
                del filtering.set
            assert len(builds) == (0 if control else
                                   len(config["notes"]) if config["variant"] == "baseline" else 1)

            # The next identical request must see a saved edit immediately.
            note = col.get_note(expected[0])
            note.tags = ["outside"]
            col.update_note(note)
            expected.remove(note.id)
            request()

    return {
        "first_ms": samples[0]["milliseconds"],
        "median_ms": statistics.median(s["milliseconds"] for s in samples[1:]),
        "samples": samples,
        "membership_builds": len(builds),
        "matched_notes": len(expected) + 1,
        "get_post_equal": True,
        "live_edit_verified": True,
        "verified": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default="e3a59e8")
    parser.add_argument("--rows", type=int, nargs="+", default=[100, 10000])
    parser.add_argument("--allowed", type=int, nargs="+", default=[0, 10, 1000],
                        help="membership-list sizes; 0 adds an equality control")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("dist/benchmarks/current-filtering.json"))
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        config = json.loads(args.worker.read_text())
        Path(config["output"]).write_text(json.dumps(run_worker(config), indent=2) + "\n")
        return
    if min(args.rows) < 1 or min(args.allowed) < 0 or args.repeats < 1:
        parser.error("rows/repeats must be positive and allowed sizes nonnegative")

    baseline = subprocess.check_output(
        ["git", "show", f"{args.baseline_ref}:tsunagi/shared/filtering.py"], cwd=ROOT)
    current = (ROOT / "tsunagi/shared/filtering.py").read_bytes()
    report = {
        "python": platform.python_version(), "anki": version("anki"),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=ROOT)),
        "baseline_ref": args.baseline_ref,
        "filter_sha256": {"baseline": hashlib.sha256(baseline).hexdigest(),
                          "current": hashlib.sha256(current).hexdigest()},
        "limits": ["Only shared filtering is swapped; all other code is current.",
                   "Real Anki and HTTP TestClient; fake Qt scheduling, no network socket.",
                   "Read-only repeats on one open collection per worker; OS caches are not cleared.",
                   "The query scans tags through Python filtering; search/index routes may bypass it."],
        "cases": [], "completed": False,
    }
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bootstrap()
    with tempfile.TemporaryDirectory(prefix="tsunagi-filter-bench-") as scratch:
        scratch = Path(scratch)
        baseline_file = scratch / "filtering_before.py"
        baseline_file.write_bytes(baseline)
        for rows in args.rows:
            seed = scratch / f"seed-{rows}"
            seed.mkdir()
            notes = []
            with collection(seed / "collection.anki2") as col:
                model = col.models.by_name("Basic")
                for i in range(rows):
                    note = col.new_note(model)
                    note.fields = [f"word {i}", "meaning"]
                    note.tags = [f"tag{i % 2000}"]
                    col.add_note(note, 1)
                    notes.append((note.id, i % 2000))
            for allowed in args.allowed:
                case = {"rows": rows, "allowed": allowed, "implementations": {}}
                order = ["baseline", "current"] if len(report["cases"]) % 2 == 0 else ["current", "baseline"]
                case["execution_order"] = order
                for variant in order:
                    print(f"rows={rows} allowed={allowed} {variant}", flush=True)
                    output = scratch / "worker-result.json"
                    config = scratch / "worker-config.json"
                    config.write_text(json.dumps({"variant": variant, "baseline_file": str(baseline_file),
                                                  "seed": str(seed), "notes": notes, "allowed": allowed,
                                                  "repeats": args.repeats, "output": str(output)}))
                    subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", str(config)],
                                   cwd=ROOT, check=True, timeout=180)
                    case["implementations"][variant] = json.loads(output.read_text())
                report["cases"].append(case)
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                print({name: round(result["median_ms"], 2) for name, result in case["implementations"].items()}, flush=True)
    report["completed"] = True
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Verified native queries: {args.output}")


if __name__ == "__main__":
    main()
