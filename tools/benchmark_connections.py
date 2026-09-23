#!/usr/bin/env python3
"""Compare connection handling in a running, disposable Anki testing profile.

Run one implementation at a time. Disable the other add-on and restart Anki when
switching between upstream AnkiConnect and Tsunagi. This runner only reads note
IDs. It neither launches Anki nor changes its collection or add-on configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.connection_bench import (
    Endpoint,
    abandon,
    action_request,
    burst,
    exchange,
    ids_digest,
    query_request,
    stalled_upload,
    summarize,
    validate_ids,
    wire_request,
)


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


async def run(args, report):
    endpoint = Endpoint.parse(args.url)
    api_key = os.environ.get(args.api_key_env)
    native = args.implementation == "native"

    async def checked(wire):
        response = await exchange(endpoint, wire, args.recovery_timeout, return_payload=True)
        if response["outcome"] != "ok":
            raise RuntimeError(f"Preflight/recovery request failed: {response}")
        return response["payload"]

    async def profile():
        payload = await checked(action_request(endpoint, "getActiveProfile", api_key=api_key))
        if payload.get("result") != args.profile:
            raise RuntimeError(f"Expected testing profile {args.profile!r}; got {payload.get('result')!r}")

    await profile()
    health = await checked(wire_request(endpoint, "/v1/health", api_key=api_key))
    is_tsunagi = "tsunagi" in str(health.get("server", "")).lower()
    is_upstream = "ankiconnect" in str(health.get("apiVersion", "")).lower()
    if ((args.implementation == "upstream" and not is_upstream)
            or (args.implementation != "upstream" and not is_tsunagi)):
        raise RuntimeError(f"Server identity does not match {args.implementation}: {health}")
    report["server_identity"] = health
    found = await checked(action_request(endpoint, "findNotes", {"query": args.query}, api_key))
    expected = ids_digest(found["result"])
    report["matched_notes"] = len(found["result"])
    report["note_ids_sha256"] = expected
    if not report["matched_notes"]:
        raise RuntimeError("Search matched no notes; choose a populated testing collection/query")

    def validate(payload):
        validate_ids(payload, native, expected)

    wire = query_request(endpoint, native, args.query, api_key)

    async def recover():
        response = await exchange(endpoint, wire, args.recovery_timeout, validate)
        if response["outcome"] != "ok":
            raise RuntimeError(f"Recovery query failed; stopping subsequent cases: {response}")
        await profile()
        await asyncio.sleep(1)  # late requests have closed sockets; allow cleanup between trials
        return response

    await recover()
    print(f"Verified {args.implementation}, profile {args.profile!r}, {report['matched_notes']} notes.", flush=True)
    save(args.output, report)
    if args.preflight_only:
        report["completed"] = True
        return

    async def record(case):
        # Checkpoint the measured outcome before attempting recovery, including failures.
        report["cases"].append(case)
        save(args.output, report)
        case["recovery"] = await recover()
        save(args.output, report)
        measurement = case.get("burst", case.get("probe", case.get("abandoned")))
        print(f"{case['scenario']} n={case.get('concurrency', 1)} trial={case['trial']}: "
              f"{measurement.get('outcomes', measurement.get('outcome'))}", flush=True)

    for concurrency in args.concurrency:
        for trial in range(1, args.repeats + 1):
            await record({"scenario": "concurrent_reads", "concurrency": concurrency,
                          "trial": trial, "timeout_seconds": args.timeout,
                          "burst": await burst(endpoint, wire, concurrency, args.timeout, validate)})

    # Same largest burst with a longer deadline distinguishes waiting from an
    # outright lost response. No retry is hidden inside the short-deadline run.
    for trial in range(1, args.repeats + 1):
        await record({"scenario": "concurrent_reads_long_deadline",
                      "concurrency": max(args.concurrency), "trial": trial,
                      "timeout_seconds": args.recovery_timeout,
                      "burst": await burst(endpoint, wire, max(args.concurrency),
                                           args.recovery_timeout, validate)})

    for complete in (False, True):
        abandoned_wire = wire if complete else wire.split(b"\r\n\r\n", 1)[0] + b"\r\n"
        for trial in range(1, args.repeats + 1):
            started = time.perf_counter()
            attempts = await asyncio.gather(*(abandon(endpoint, abandoned_wire, args.timeout)
                                             for _ in range(args.abort_connections)))
            await record({"scenario": "disconnect_after_request" if complete else "disconnect_mid_headers",
                          "concurrency": args.abort_connections, "trial": trial,
                          "abandoned": summarize(attempts, (time.perf_counter() - started) * 1000)})

    # Use the same harmless, incomplete POST body on all servers. Independent
    # probes still use the chosen implementation's read endpoint.
    partial = action_request(endpoint, "findNotes", {"query": args.query}, api_key)[:-1]
    for trial in range(1, args.repeats + 1):
        await record({"scenario": "stalled_upload", "trial": trial,
                      "hold_seconds": 2.1, "probe_timeout_seconds": 1,
                      "probe": await stalled_upload(endpoint, partial, wire, args.timeout, validate)})
    await profile()
    report["completed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--profile", required=True, help="Exact name of the disposable profile; checked before testing")
    parser.add_argument("--implementation", required=True, choices=("upstream", "shim", "native"))
    parser.add_argument("--query", default="", help="Identical Anki search for every implementation; default: all notes")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 16, 64, 256])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--recovery-timeout", type=float, default=30)
    parser.add_argument("--abort-connections", type=int, default=64)
    parser.add_argument("--api-key-env", default="TSUNAGI_BENCH_API_KEY")
    parser.add_argument("--server-label", default="", help="Record the installed add-on revision/version if known")
    parser.add_argument("--preflight-only", action="store_true", help="Check identity, profile and equivalent results without load tests")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (any(not 1 <= value <= 1024 for value in args.concurrency)
            or not 1 <= args.abort_connections <= 1024 or args.repeats < 1
            or not 0 < args.timeout <= args.recovery_timeout <= 120):
        parser.error("Use 1..1024 connections, positive repeats, and 0 < timeout <= recovery-timeout <= 120")
    if args.output.exists():
        parser.error("Output already exists; choose a new path so an earlier run is not overwritten")
    report = {"schema": 1, "started_at": datetime.now(timezone.utc).isoformat(),
              "mode": "live_anki_tcp", "python": sys.version, "platform": platform.platform(),
              "config": {key: str(value) if isinstance(value, Path) else value
                         for key, value in vars(args).items() if key != "api_key_env"},
              "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in (Path(__file__), Path(__file__).with_name("connection_bench.py"))},
              "limits": ["Read-only note-ID queries; no write cancellation or media uploads measured.",
                         "New TCP connection per attempt; no connection pool or automatic retries.",
                         "Aborted-after-send counts client actions, not confirmed server execution.",
                         "Successful response latency excludes failed attempts; all outcomes are retained.",
                         "Operator must disable the other add-on and restart Anki when switching servers."],
              "cases": [], "completed": False}
    try:
        asyncio.run(run(args, report))
    except (Exception, KeyboardInterrupt) as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(args.output, report)


if __name__ == "__main__":
    main()
