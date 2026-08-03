#!/usr/bin/env python3
"""
Copy the add-on source into Anki's installed add-on folder, so a running Anki
can pick it up without a reinstall.

    python tools/dev_sync.py
    # then in Anki's debug console (Ctrl+Shift+;):
    #     import tsunagi; tsunagi.reload_addon()

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
        "Install dist/tsunagi-0.0.1.ankiaddon through Anki once, or pass "
        "--dest / set TSUNAGI_ADDON_DIR."
    )


def copy_tree(src: Path, dest: Path) -> int:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return sum(1 for _ in dest.rglob("*.py"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", help="installed add-on folder (default: auto-detect)")
    ap.add_argument("--full", action="store_true",
                    help="also copy lib/ (only needed after a dependency rebuild)")
    args = ap.parse_args()

    dest = find_dest(args.dest)
    print(f"-> {dest}")

    if not (dest / "lib" / "shared").is_dir() and not args.full:
        print("warning: no lib/shared at the destination - install the built "
              ".ankiaddon once, or re-run with --full")

    count = copy_tree(ROOT / SOURCE_TREE, dest / SOURCE_TREE)
    print(f"   {SOURCE_TREE}/  ({count} modules)")

    for name in SOURCE_FILES:
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, dest / name)
            print(f"   {name}")

    if args.full:
        lib = ROOT / "lib"
        if not lib.is_dir():
            sys.exit("lib/ not built - run tools/build_addon.py first")
        copy_tree(lib, dest / "lib")
        print("   lib/")

    print("\nIn Anki's debug console (Ctrl+Shift+;):")
    print("    import tsunagi; tsunagi.reload_addon()")
    print("\nEditing __init__.py or lib/ still needs a full Anki restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
