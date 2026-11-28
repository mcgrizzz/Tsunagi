"""
Add one benchmark run to website/data/benchmarks.json, the site's history of
runs, from the client-workload reports in dist/benchmarks/
(tools/benchmark_workloads.py): the versions measured, the collection's size,
and per workload and API, the
median, every timed trial, requests and bytes, and (from reports that log
them) the median trial's requests in order. Leaves out what the reports hold
about the profile: its name, result samples drawn from its notes, and the note
IDs in request paths.

    python tools/extract_benchmarks.py --date 2026-11-27 --tsunagi 0.7.8 --anki 26.09.4 --ankiconnect "AnkiWeb, 22 Nov 2026" \
        --conditions "Other add-ons off, Anki minimized (tools/bench_switch.py)"
"""
import argparse
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.benchmark_workloads import TIMEOUT, WORKLOADS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "website/data/benchmarks.json"
# Report name -> the name the site shows.
IMPLEMENTATIONS = {"upstream": "AnkiConnect", "shim": "AnkiConnect Shim", "native": "Tsunagi API"}
# What a workload's request count grows with: a key of the run's collection size.
SCALES = {w.name: w.scales_with for w in WORKLOADS}


def extract(date: str, tsunagi: str, anki: str, ankiconnect: str, conditions: str) -> dict:
    """One run: every report for the date, per API (workloads-<impl>-<date>*.json,
    oldest first: a run stopped by a failure can be finished or retried in a
    later report). A workload with no timed trial anywhere is kept as failed,
    with why; a later report's measurement replaces an earlier one's."""
    workloads, size, limits = {}, None, []
    for impl, label in IMPLEMENTATIONS.items():
        paths = (ROOT / "dist/benchmarks").glob(f"workloads-{impl}-{date}*.json")
        reports = sorted((json.loads(p.read_text(encoding="utf-8")) for p in paths), key=lambda r: r["started_at"])
        if not reports:
            raise SystemExit(f"No {impl} report for {date} in dist/benchmarks")
        for report in reports:
            # Older reports have only the note count.
            size = report.get("collection") or size or {"notes": report.get("baseline_notes")}
            limits = report["limits"]
            for w in report["workloads"]:
                entry = workloads.setdefault(w["workload"], {"name": w["workload"], "source": w["source"], "results": {},
                                                             "scales_with": SCALES.get(w["workload"])})
                timed = w["trials"][1:]   # the first run warms up; medians leave it out
                if not timed:
                    timeout = report["config"].get("timeout", TIMEOUT)
                    if "median_ms" not in entry["results"].get(label, {}):   # a later failure replaces an earlier one, never a time
                        entry["results"][label] = {"failed": failed(report.get("failure", ""), timeout)}
                    continue
                middle = sorted(timed, key=lambda t: t["elapsed_ms"])[len(timed) // 2]
                entry["results"][label] = {
                    "median_ms": round(w["median_ms"], 1),
                    "trials_ms": [round(t["elapsed_ms"], 1) for t in timed],
                    "requests": timed[0]["requests"],
                    "response_bytes": timed[0]["response_bytes"],
                }
                if "request_log" in middle:
                    entry["results"][label]["log"] = [
                        {"what": re.sub(r"/\d+", "/{id}", r["what"].split("?")[0]), "start_ms": round(r["start_ms"], 1),
                         "end_ms": round(r["end_ms"], 1), "bytes": r["bytes"]} for r in middle["request_log"]]
    return {"measured": date, "tsunagi": tsunagi, "anki": anki, "ankiconnect": ankiconnect,
            "conditions": conditions, "collection": size, "limits": limits, "workloads": list(workloads.values())}


def failed(failure: str, timeout: float) -> str:
    """Why a run stopped, as the site says it."""
    if "'outcome': 'timeout'" in failure:
        return f"no answer within {timeout:g} s"
    return failure or "the run stopped before a timed trial"


def save(run: dict) -> None:
    """Add the run to the site's history, replacing one from the same date; newest first."""
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"runs": []}
    runs = [r for r in old.get("runs", [old] if "workloads" in old else []) if r["measured"] != run["measured"]]
    runs = sorted(runs + [run], key=lambda r: r["measured"], reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", required=True)
    parser.add_argument("--tsunagi", required=True)
    parser.add_argument("--anki", required=True)
    parser.add_argument("--ankiconnect", required=True, help="which AnkiConnect build, as the site names it")
    parser.add_argument("--conditions", required=True,
                        help="the state Anki was measured in (other add-ons, window), as the site says it")
    args = parser.parse_args()
    save(extract(args.date, args.tsunagi, args.anki, args.ankiconnect, args.conditions))
