#!/usr/bin/env python3
"""
Compare each tested tool's latest code with the commit its declaration was
read at (tests/clients/<name>/sites.json): which actions' call sites changed,
appeared or went since. The weekly checks (.github/workflows/scheduled.yml)
run it; a change is a report for the owner, who decides whether to recheck
the tool (tools/scan_client.py).

    python tools/check_clients.py                # every tool
    python tools/check_clients.py yomitan jl     # some
    python tools/check_clients.py --save website/data/tools-check.json

Each tool's default branch is cloned shallow into a temporary folder and only
read as text, never run. A tool whose call sites all sit two or more folders
deep in one place (a monorepo, such as raycast/extensions) gets only that
folder. Exits 1 when any tool changed or couldn't be cloned.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from clients.support import clients  # noqa: E402

from tools.scan_client import commit, compare, scan  # noqa: E402


def folder(sites):
    """The one folder, two or more deep, that holds every call site; None for the whole repo."""
    paths = [site["at"].rpartition(":")[0].split("/")[:-1] for found in sites.values() for site in found]
    common = os.path.commonprefix(paths) if paths else []
    return "/".join(common) if len(common) >= 2 else None


def check(name, module, scratch):
    """{"latest": commit, "changed": [[action, state], ...]} or {"error": why}."""
    saved = json.loads((ROOT / "tests/clients" / name / "sites.json").read_text(encoding="utf-8"))
    checkout = Path(scratch) / name
    only = folder(saved["sites"])
    clone = ["git", "clone", "--quiet", "--depth", "1", "--filter=blob:none"]
    run = dict(capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, timeout=600)
    try:
        cloned = subprocess.run(clone + (["--sparse"] if only else []) + [module.CLIENT["repo"], str(checkout)], **run)
        if cloned.returncode == 0 and only:
            cloned = subprocess.run(["git", "-C", str(checkout), "sparse-checkout", "set", only], **run)
    except subprocess.TimeoutExpired:
        return {"error": "the clone took over 10 minutes"}
    if cloned.returncode != 0:
        return {"error": (cloned.stderr.strip().splitlines() or ["git clone failed"])[-1]}
    sites, _hints = scan(checkout)
    return {"latest": commit(checkout), "changed": [[action, state] for action, state, _ in compare(saved["sites"], sites)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].replace("\n", " "))
    parser.add_argument("names", nargs="*", help="tools to check (tests/clients folder names); all when none")
    parser.add_argument("--save", type=Path, help="also write the result as JSON here")
    args = parser.parse_args()
    found = clients()
    unknown = sorted(set(args.names) - set(found))
    if unknown:
        parser.error(f"no such tool: {', '.join(unknown)}")
    result = {"checked": datetime.date.today().isoformat(), "tools": {}}
    with tempfile.TemporaryDirectory() as scratch:
        for name in args.names or sorted(found):
            module = found[name]
            r = result["tools"][name] = {"read": module.CLIENT["commit"], **check(name, module, scratch)}
            if "error" in r:
                print(f"{name}: couldn't clone {module.CLIENT['repo']}: {r['error']}")
            elif r["changed"]:
                n = len(r["changed"])
                print(f"{name}: {r['read']} -> {r['latest']}: {n} action{'s' if n > 1 else ''} changed: "
                      + ", ".join(f"{a} ({s})" for a, s in r["changed"]))
            else:
                print(f"{name}: {r['read']} -> {r['latest']}: no change")
    if args.save:
        args.save.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return 1 if any("error" in r or r["changed"] for r in result["tools"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
