"""
Find where a client's code talks to AnkiConnect (6.135), with no LLM: every
AnkiConnect action it names, where, and hints about its envelope.

    python tools/scan_client.py CHECKOUT                 # print what it finds
    python tools/scan_client.py CHECKOUT --save NAME     # write tests/clients/NAME/sites.json
    python tools/scan_client.py CHECKOUT --compare NAME  # what changed since NAME's sites.json
    python tools/scan_client.py --coverage NAME          # actions NAME's code names that SENDS leaves out

The checkout is only read as text, never run. Each call site is hashed (its
line and the lines around it), so --compare names the actions whose code
changed: a report for the owner, who decides whether to recheck (a client is
rechecked only when the owner asks).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Not the client's own behaviour: dependencies, build output, its tests and
# docs, and copies of AnkiConnect itself (its AnkiWeb id is in the path).
SKIP_DIRS = {".git", "node_modules", "dist", "build", "vendor", "third_party", "__pycache__",
             "target", ".venv", "venv", "coverage", ".next", "out", "test", "tests", "Tests",
             "__tests__", "spec", "fixtures", "docs", "2055492159"}
SKIP_FILES = re.compile(r"(\.min\.js|\.map|\.lock|lock\.json|\.svg|\.png|\.jpg|\.gif|\.woff2?|\.ttf|\.ico|"
                        r"\.pdf|\.zip|\.apkg|\.anki2|\.mp3|\.ogg|\.mp4|\.md|\.rst|\.txt|"
                        r"[._](test|spec)\.[a-z]+|^test_.*\.py)$", re.I)
CONTEXT = 3  # lines either side that count as the call site
# Action names that are also ordinary words: counted only in files that look
# like AnkiConnect code (two other actions named, or its port).
COMMON = {"version", "multi", "sync", "suspend", "unsuspend"}


def actions():
    """AnkiConnect's action names, from the parity doc's table (tests/test_parity_doc.py keeps it current)."""
    text = (ROOT / "docs/ankiconnect_parity.md").read_text(encoding="utf-8")
    return sorted(set(re.findall(r"^\| `([a-zA-Z]+)` \|", text, re.M)))


def files(checkout: Path):
    for path in sorted(checkout.rglob("*")):
        rel = path.relative_to(checkout)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file() or SKIP_FILES.search(path.name):
            continue
        if path.stat().st_size > 1_000_000:
            continue
        try:
            yield rel.as_posix(), path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue


def scan(checkout: Path):
    names = actions()
    # An action named as a string ("addNote", 'addNote', `addNote`), or called
    # as a wrapper library's method (yanki-connect's client.note.addNote(...)).
    alternatives = "|".join(names)
    quoted = re.compile(r"""["'`](%s)["'`]|\.(%s)\(""" % (alternatives, alternatives))
    sites, hints = {}, {"version": set(), "port_8765": [], "multi": []}
    version = re.compile(r"""["']?version["']?\s*[:=]\s*(\d)\b""")
    for rel, lines in files(checkout):
        text = "\n".join(lines)
        named = {a or b for a, b in quoted.findall(text)}
        relevant = len(named - COMMON) >= 2 or "8765" in text
        if not named and "8765" not in text:
            continue
        for i, line in enumerate(lines):
            for action in (a or b for a, b in quoted.findall(line)):
                if action in COMMON and not relevant:
                    continue
                window = "\n".join(lines[max(0, i - CONTEXT): i + CONTEXT + 1])
                sites.setdefault(action, []).append({
                    "at": f"{rel}:{i + 1}",
                    "hash": hashlib.sha256(window.encode()).hexdigest()[:16],
                })
            if "8765" in line:
                hints["port_8765"].append(f"{rel}:{i + 1}")
            if relevant:
                for v in version.findall(line):
                    hints["version"].add(int(v))
    hints["multi"] = [s["at"] for s in sites.get("multi", [])]
    hints["version"] = sorted(hints["version"])
    return sites, hints


def commit(checkout: Path):
    try:
        return subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
                                       text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def compare(old, new):
    """Each action whose call sites changed, appeared or went."""
    out = []
    for action in sorted(set(old) | set(new)):
        before = sorted(s["hash"] for s in old.get(action, []))
        after = sorted(s["hash"] for s in new.get(action, []))
        if before != after:
            state = "new" if not before else "gone" if not after else "changed"
            out.append((action, state, [s["at"] for s in new.get(action, [])] or
                        [s["at"] for s in old.get(action, [])]))
    return out


def covered(name):
    """The actions a client's SENDS names, and those its multi batches."""
    sys.path[:0] = [str(ROOT / "lib/shared"), str(ROOT), str(ROOT / "tests")]
    from clients.support import clients

    sends = clients()[name].SENDS
    shapes = sends.get("multi", ([], ()))[0]
    return set(sends) | {a.get("action") for s in shapes for a in s.get("actions", ()) if isinstance(a, dict)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("checkout", type=Path, nargs="?")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--coverage", metavar="NAME")
    group.add_argument("--save", metavar="NAME")
    group.add_argument("--compare", metavar="NAME")
    args = parser.parse_args()
    if args.coverage:
        saved = json.loads((ROOT / "tests/clients" / args.coverage / "sites.json").read_text(encoding="utf-8"))
        missing = sorted(set(saved["sites"]) - covered(args.coverage))
        print(f"{args.coverage}: {len(saved['sites']) - len(missing)} of {len(saved['sites'])} actions covered")
        for action in missing:
            print(f"  {action}: {', '.join(s['at'] for s in saved['sites'][action][:3])}")
        return 0
    if args.checkout is None:
        parser.error("a checkout is needed, except with --coverage")
    sites, hints = scan(args.checkout)
    if args.save:
        out = {"commit": commit(args.checkout), "sites": sites, "hints": hints}
        path = ROOT / "tests/clients" / args.save / "sites.json"
        path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{args.save}: {len(sites)} actions, {sum(map(len, sites.values()))} call sites at {out['commit']}")
    elif args.compare:
        saved = json.loads((ROOT / "tests/clients" / args.compare / "sites.json").read_text(encoding="utf-8"))
        changes = compare(saved["sites"], sites)
        print(f"{args.compare}: {saved['commit']} -> {commit(args.checkout)}: "
              f"{len(changes) or 'no'} actions changed")
        for action, state, where in changes:
            print(f"  {action} ({state}): {', '.join(where[:4])}")
    else:
        for action, found in sorted(sites.items()):
            print(f"{action}: {', '.join(s['at'] for s in found[:5])}{' ...' if len(found) > 5 else ''}")
        print(f"\nversion values: {hints['version']}; port 8765 at: {', '.join(hints['port_8765'][:5])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
