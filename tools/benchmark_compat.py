"""Compare bulk AnkiConnect/shim/native processing in restored disposable collections.

Requires Python 3.12+, Anki, the test dependencies, and a built lib/shared.
This is an opt-in measurement tool, not a latency gate in the test suite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

from compat_bench.runtime import ROOT, bootstrap, collection, run_worker
from compat_bench.workloads import seed_collection


def numbers(text):
    try:
        values = list(dict.fromkeys(int(part) for part in text.split(",")))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc
    if not values or any(value < 0 for value in values):
        raise argparse.ArgumentTypeError("values must be non-negative")
    return values


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", default=os.environ.get("TSUNAGI_ANKICONNECT_CHECKOUT"))
    parser.add_argument("--output", type=Path, default=Path("/tmp/tsunagi-bulk-benchmark.json"))
    parser.add_argument("--read-sizes", type=numbers, default=[1000, 10000])
    parser.add_argument("--write-sizes", type=numbers, default=[100, 1000])
    parser.add_argument("--batches", type=numbers, default=[0], help="card response sizes for all implementations; 0 means all")
    parser.add_argument("--repeats", type=int, default=5, help="repeated samples after a first-use sample")
    parser.add_argument("--media-bytes", type=int, default=16384, help="bytes per image and audio attachment")
    parser.add_argument("--worker-timeout", type=float, default=1200,
                        help="whole worker process limit, including restored trials and profiling")
    parser.add_argument("--workloads", default="read_cards,add_text,add_media_new,add_media_existing")
    parser.add_argument("--implementations", default="upstream,shim,native")
    parser.add_argument("--worker-config", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error("the pinned AnkiConnect source requires Python 3.12 or newer")
    if args.worker_config is None:
        if not args.checkout:
            parser.error("supply --checkout or TSUNAGI_ANKICONNECT_CHECKOUT")
        if args.repeats < 2 or args.media_bytes < 128 or args.worker_timeout <= 0:
            parser.error("repeats must be >=2, media-bytes >=128, and worker-timeout positive")
    args.workloads = args.workloads.split(",")
    args.implementations = args.implementations.split(",")
    if not set(args.workloads) <= {"read_cards", "add_text", "add_media_new", "add_media_existing"}:
        parser.error("unknown workload")
    if not set(args.implementations) <= {"upstream", "shim", "native"}:
        parser.error("unknown implementation")
    if len(set(args.implementations)) != len(args.implementations):
        parser.error("implementations must be unique")
    return args


def summarize(result, count):
    timings = [sample["milliseconds"] for sample in result["samples"][1:]]
    median = statistics.median(timings)
    return {"first_ms": result["samples"][0]["milliseconds"], "median_ms": median,
            "min_ms": min(timings), "max_ms": max(timings),
            "items_per_second": count * 1000 / median if median else None}


def run_case(args, case, scratch, index):
    case_dir = scratch / str(index)
    seed = case_dir / "seed"
    seed.mkdir(parents=True)
    with collection(seed / "collection.anki2") as col:
        seed_collection(col, case)
    result = {"workload": case, "implementations": {}}
    # Alternate implementation order between cases; each worker is a fresh process.
    shift = index % len(args.implementations)
    order = args.implementations[shift:] + args.implementations[:shift]
    result["execution_order"] = order
    for implementation in order:
        print(f"  {implementation}: running sequentially", flush=True)
        config_path = case_dir / f"{implementation}.config.json"
        output_path = case_dir / f"{implementation}.result.json"
        config_path.write_text(json.dumps({"case": case, "implementation": implementation,
                                          "checkout": str(Path(args.checkout).resolve()),
                                          "seed": str(seed), "scratch": str(case_dir),
                                          "repeats": args.repeats, "output": str(output_path)}))
        try:
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker-config", str(config_path)],
                cwd=ROOT, capture_output=True, text=True, timeout=args.worker_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            progress = Path(str(output_path) + ".progress")
            result["incomplete_worker"] = {
                "implementation": implementation,
                "progress": json.loads(progress.read_text()) if progress.exists() else None,
            }
            failure_path = args.output.with_name(args.output.stem + f"-failed-case-{index}.json")
            failure_path.write_text(json.dumps(result, indent=2) + "\n")
            raise RuntimeError(f"{implementation}: whole worker exceeded {args.worker_timeout}s; "
                               f"partial evidence: {failure_path}") from exc
        if completed.returncode:
            raise RuntimeError(f"{implementation} {case}:\n{completed.stderr[-6000:]}\n{completed.stdout[-2000:]}")
        measured = json.loads(output_path.read_text())
        measured["summary"] = summarize(measured, case["size"])
        result["implementations"][implementation] = measured
    if len({entry["fingerprint"] for entry in result["implementations"].values()}) != 1:
        raise RuntimeError(f"equivalent-result verification failed: {case}")
    result["equal_results"] = True if len(order) > 1 else None
    return result


def main():
    args = parse_args()
    if args.worker_config:
        config = json.loads(args.worker_config.read_text())
        Path(config["output"]).write_text(json.dumps(run_worker(config), indent=2) + "\n")
        return
    args.output = args.output.resolve()
    args.checkout = str(Path(args.checkout).resolve())
    bootstrap()
    from tools.upstream_reference import UPSTREAM_REVISION
    from tsunagi.shared.version import ADDON_VERSION
    cases = [{"kind": "read_cards", "size": size, "batch": batch, "media_bytes": args.media_bytes}
             for size in args.read_sizes for batch in args.batches if size]
    cases.extend({"kind": kind, "size": size, "batch": 0, "media_bytes": args.media_bytes}
                 for size in args.write_sizes if size
                 for kind in ("add_text", "add_media_new", "add_media_existing"))
    cases = [case for case in cases if case["kind"] in args.workloads]
    report = {
        "schema": 2, "mode": "headless_processing",
        "python": platform.python_version(), "anki": version("anki"),
        "tsunagi": ADDON_VERSION, "platform": platform.platform(),
        "tsunagi_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=ROOT)),
        "benchmark_files_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("tools/benchmark_compat.py", "tools/compat_bench/runtime.py",
                         "tools/compat_bench/workloads.py", "tools/compat_bench/native.py", "tools/upstream_reference.py",
                         "tests/fakes/anki_stubs.py")},
        "upstream_commit": UPSTREAM_REVISION, "repeats": args.repeats,
        "limits": [
            "Real Anki backend; fake Qt scheduling and upstream GUI edit hooks disabled.",
            "Upstream original HTTP wrapper versus FastAPI TestClient; no listening API socket or real UI.",
            "First/repeated mean first-in-process and restored repeats; OS caches are not cleared.",
            "Worker peak RSS includes imports, requests, decoding, profiling and verification.",
            "Inline base64 media only; network downloads, playback and GUI responsiveness are unmeasured.",
            "One synthetic Basic note type, one card per note, no review history or rendered LaTeX.",
        ], "cases": [], "failures": [], "completed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tsunagi-bulk-benchmark-") as scratch:
        for index, case in enumerate(cases):
            print(f"[{index + 1}/{len(cases)}] {case['kind']} size={case['size']} batch={case['batch']}", flush=True)
            try:
                result = run_case(args, case, Path(scratch), index)
            except Exception as exc:
                report["failures"].append({"workload": case, "error": str(exc)})
                args.output.write_text(json.dumps(report, indent=2) + "\n")
                raise
            report["cases"].append(result)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            print("  " + ", ".join(f"{name}: {entry['summary']['median_ms']:.1f} ms"
                                    for name, entry in result["implementations"].items()), flush=True)
    report["completed"] = True
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Verified {len(cases)} workloads. Results: {args.output}")


if __name__ == "__main__":
    main()
