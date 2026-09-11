#!/usr/bin/env python3
"""
Copy the add-on source into Anki's installed add-on folder, so a running Anki
can pick it up without a reinstall.

    python tools/dev_sync.py --watch    # leave running: save a file, done

With `dev_watch_seconds` set in the add-on config, Anki notices the copy and
restarts its server on its own, so --watch means editing a file is the entire
workflow. Without it, sync is one command and the reload is one line in Anki's
debug console (Ctrl+Shift+;):

    import tsunagi; tsunagi.reload_addon()

The vendored libraries in lib/ are skipped by default - they only change when
the lockfile does, and copying ~1 MB every iteration is wasted work. Pass
--full when you have rebuilt them.

This does NOT install the add-on. Install the built .ankiaddon once through
Anki so lib/shared and meta.json exist; after that this keeps the source in
sync.
"""
import argparse
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "tsunagi"

# Everything the add-on needs at run time, minus lib/ (see --full).
SOURCE_TREE = "tsunagi"
SOURCE_FILES = ("__init__.py", "manifest.json", "config.json", "config.md", "README.md")


def candidate_dirs():
    """Where Anki keeps add-ons, most specific first."""
    env = os.environ.get("TSUNAGI_ADDON_DIR")
    if env:
        yield Path(env)

    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:                                   # native Windows
        roots.append(Path(appdata) / "Anki2")
    # WSL reaching the Windows profile
    for users in Path("/mnt/c/Users").glob("*"):
        roots.append(users / "AppData/Roaming/Anki2")
    roots.append(Path.home() / ".local/share/Anki2")                    # Linux
    roots.append(Path.home() / "Library/Application Support/Anki2")     # macOS

    for root in roots:
        yield root / "addons21" / PACKAGE


def find_dest(explicit=None):
    if explicit:
        dest = Path(explicit)
        if not dest.is_dir():
            sys.exit(f"--dest does not exist: {dest}")
        return dest
    for path in candidate_dirs():
        if path.is_dir():
            return path
    sys.exit(
        "Could not find an installed Tsunagi add-on folder.\n"
        "Install a built dist/tsunagi-<version>.ankiaddon through Anki once, or pass "
        "--dest / set TSUNAGI_ADDON_DIR."
    )


def copy_tree(src: Path, dest: Path) -> int:
    # Stage beside the destination, then swap. The old rmtree-then-copytree
    # left a window where the package was half-written on disk - an
    # interrupted sync (Ctrl+C, AV scan, Anki booting mid-copy) stranded a
    # partial tree, which surfaces in Anki as a boot-time
    # ModuleNotFoundError for whichever module didn't make it.
    stage = dest.parent / (dest.name + ".syncing")
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(src, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if dest.exists():
        shutil.rmtree(dest)
    os.replace(stage, dest)
    return sum(1 for _ in dest.rglob("*.py"))


def source_stamp() -> tuple:
    """(file count, newest mtime) across the source we copy."""
    newest = 0.0
    count = 0
    for path in (ROOT / SOURCE_TREE).rglob("*.py"):
        try:
            newest = max(newest, path.stat().st_mtime)
            count += 1
        except OSError:
            pass
    for name in SOURCE_FILES:
        src = ROOT / name
        if src.is_file():
            newest = max(newest, src.stat().st_mtime)
    return count, newest


def sync(dest: Path, full: bool, verbose: bool = True) -> None:
    count = copy_tree(ROOT / SOURCE_TREE, dest / SOURCE_TREE)
    if verbose:
        print(f"   {SOURCE_TREE}/  ({count} modules)")

    for name in SOURCE_FILES:
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, dest / name)
            if verbose:
                print(f"   {name}")

    if full:
        lib = ROOT / "lib"
        if not lib.is_dir():
            sys.exit("lib/ not built - run tools/build_addon.py first")
        copy_tree(lib, dest / "lib")
        if verbose:
            print("   lib/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", help="installed add-on folder (default: auto-detect)")
    ap.add_argument("--full", action="store_true",
                    help="also copy lib/ (only needed after a dependency rebuild)")
    ap.add_argument("--watch", action="store_true",
                    help="stay running and re-sync whenever the source changes")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="seconds between checks when watching (default 1)")
    args = ap.parse_args()

    dest = find_dest(args.dest)
    print(f"-> {dest}")

    if not (dest / "lib" / "shared").is_dir() and not args.full:
        print("warning: no lib/shared at the destination - install the built "
              ".ankiaddon once, or re-run with --full")

    sync(dest, args.full)

    if not args.watch:
        print("\nIn Anki's debug console (Ctrl+Shift+;):")
        print("    import tsunagi; tsunagi.reload_addon()")
        print("...or set dev_watch_seconds in the add-on config and Anki will "
              "reload itself.")
        print("\nEditing __init__.py or lib/ still needs a full Anki restart.")
        return 0

    print(f"\nwatching {ROOT / SOURCE_TREE} (Ctrl+C to stop)")
    print("set dev_watch_seconds in the add-on config so Anki reloads itself too")
    stamp = source_stamp()
    try:
        while True:
            time.sleep(args.interval)
            current = source_stamp()
            if current == stamp:
                continue
            stamp = current
            sync(dest, args.full, verbose=False)
            print(f"  synced {time.strftime('%H:%M:%S')}  ({current[0]} modules)")
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
