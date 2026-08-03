#!/usr/bin/env python3
"""
Diff docs/ankiconnect_parity.md against a local AnkiConnect checkout.

`tests/test_parity_doc.py` checks the doc against our own registry, which
catches us drifting from our own claim. It cannot catch *upstream* drifting
from us, because CI has no copy of AnkiConnect. Run this by hand after
pulling the reference clone:

    cd ~/refs/anki-connect && git pull
    python tools/check_parity.py

Exits non-zero if upstream has gained or dropped an action.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "ankiconnect_parity.md"
DEFAULT_CLONE = Path.home() / "refs" / "anki-connect"

ROW = re.compile(r"^\|\s*`([A-Za-z]+)`\s*\|\s*([A-Za-z0-9-]+)\s*\|")
# The decorator sits on the line before the def, so pair them up.
API = re.compile(r"@util\.api\(\)\s*\n\s*def\s+([A-Za-z_]+)\s*\(")


def documented():
    return {m.group(1) for m in (ROW.match(line) for line
                                 in DOC.read_text(encoding="utf-8").splitlines()) if m}


def upstream(clone: Path):
    plugin = clone / "plugin" / "__init__.py"
    if not plugin.is_file():
        sys.exit(f"no AnkiConnect checkout at {clone} (expected {plugin})")
    return set(API.findall(plugin.read_text(encoding="utf-8")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clone", type=Path, default=DEFAULT_CLONE,
                    help=f"AnkiConnect checkout (default: {DEFAULT_CLONE})")
    args = ap.parse_args()

    ours, theirs = documented(), upstream(args.clone)
    added = sorted(theirs - ours)
    dropped = sorted(ours - theirs)

    print(f"documented: {len(ours)}   upstream: {len(theirs)}")
    for name in added:
        print(f"  + {name}   NEW upstream - add a row")
    for name in dropped:
        print(f"  - {name}   gone upstream - we still list it")

    if not added and not dropped:
        print("in sync")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
