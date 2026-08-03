#!/usr/bin/env python3
"""
Builds a single .ankiaddon ZIP that vendors pure-Python deps under lib/shared/.

All runtime dependencies are pinned in tools/requirements.lock.txt and must be
available as pure-Python (none-any) wheels. Downloads are constrained to
pure wheels (--implementation py --abi none --platform any), wheels are
selected strictly by lockfile pin (stale cache entries are ignored), and the
build fails loudly if any compiled artifact would end up in lib/shared/.

Usage:
  python tools/build_addon.py [--refresh] [--offline]

Version is read from tools/version.py (VERSION = "...").
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# --- Repository layout --------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]   # repo root
TOOLS = ROOT / "tools"
PKG_ROOT = ROOT / "tsunagi"                  # your package code (included in ZIP)
LIB = ROOT / "lib"                           # vendored deps go here
SHARED = LIB / "shared"
DIST = ROOT / "dist"
META = ROOT / "meta.json"
LOCKFILE = TOOLS / "requirements.lock.txt"

# Persistent local wheel cache
CACHE = ROOT / ".wheelhouse"
CACHE_PURE = CACHE / "pure"

# Minimum supported interpreter (Anki 23.10 bundles Python 3.9). Wheels are
# resolved against this version so newer-only wheels can't slip in.
MIN_PYTHON = "3.9"

# --- CLI ----------------------------------------------------------------------

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="clear local wheel cache before build")
    ap.add_argument("--offline", action="store_true", help="do not attempt network; use cached wheels only")
    return ap.parse_args()

# --- Helpers ------------------------------------------------------------------

def sh(cmd, **kw):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)

def clean_lib_and_dist():
    if LIB.exists():
        shutil.rmtree(LIB)
    LIB.mkdir(parents=True, exist_ok=True)
    SHARED.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)

def prepare_cache(refresh: bool):
    if refresh and CACHE.exists():
        shutil.rmtree(CACHE)
    CACHE_PURE.mkdir(parents=True, exist_ok=True)

def read_version() -> str:
    ns = {}
    exec((TOOLS / "version.py").read_text(encoding="utf-8"), ns)
    return ns["VERSION"]

def bump_meta_mod():
    if META.exists():
        data = json.loads(META.read_text(encoding="utf-8"))
        data["mod"] = int(time.time())
        META.write_text(json.dumps(data, indent=2), encoding="utf-8")

def _canonical(name: str) -> str:
    # PEP 503 normalization, used to compare lockfile names to wheel filenames
    return re.sub(r"[-_.]+", "-", name).lower()

def read_lockfile() -> list[tuple[str, str]]:
    """Parse tools/requirements.lock.txt into (name, version) pins."""
    pins: list[tuple[str, str]] = []
    for raw in LOCKFILE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise RuntimeError(f"lockfile entry is not an exact pin: {raw!r}")
        name, version = (part.strip() for part in line.split("==", 1))
        pins.append((name, version))
    if not pins:
        raise RuntimeError(f"no pins found in {LOCKFILE}")
    return pins

def unzip_wheel_to_shared(whl: Path):
    with zipfile.ZipFile(whl) as z:
        names = z.namelist()
        for n in names:
            if n.endswith("/") or ".dist-info/" in n:
                continue
            if ".data/" in n:
                continue  # handle purelib below
            out_path = SHARED / n
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(out_path, "wb") as dst:
                dst.write(src.read())
        for n in names:
            if ".data/purelib/" in n and not n.endswith("/"):
                rel = n.split(".data/purelib/", 1)[1]
                out_path = SHARED / rel
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as src, open(out_path, "wb") as dst:
                    dst.write(src.read())

# --- Cache-aware vendoring ----------------------------------------------------

def _find_wheel(name: str, version: str) -> Path:
    """Find exactly one cached wheel matching a lockfile pin."""
    matches = []
    for whl in CACHE_PURE.glob("*.whl"):
        parts = whl.name.split("-")
        if len(parts) < 3:
            continue
        if _canonical(parts[0]) == _canonical(name) and parts[1] == version:
            matches.append(whl)
    if not matches:
        raise RuntimeError(
            f"no cached wheel for {name}=={version}; run without --offline (or with --refresh)"
        )
    if len(matches) > 1:
        raise RuntimeError(f"ambiguous wheels for {name}=={version}: {[m.name for m in matches]}")
    whl = matches[0]
    if not whl.name.endswith("-none-any.whl"):
        raise RuntimeError(f"{whl.name} is not a pure-Python wheel; refusing to vendor it")
    return whl

def _assert_pure():
    """Fail the build if any compiled artifact landed in lib/shared/."""
    binaries = [p for p in SHARED.rglob("*") if p.suffix in {".pyd", ".so", ".dylib"}]
    if binaries:
        listing = "\n".join(str(p.relative_to(SHARED)) for p in binaries)
        raise RuntimeError(f"compiled artifacts found in lib/shared:\n{listing}")

def vendor_pure_python_deps(offline: bool) -> list[Path]:
    """
    Ensure the exact lockfile-pinned pure wheels exist in CACHE_PURE (download
    unless offline), then unpack only those into lib/shared/.
    """
    if not offline:
        # --implementation py --abi none --platform any: pip only accepts
        # none-any wheels, so a package without a pure wheel fails loudly
        # instead of silently vendoring a platform-specific binary.
        sh([sys.executable, "-m", "pip", "download",
            "--no-deps", "-r", str(LOCKFILE),
            "--only-binary=:all:",
            "--implementation", "py", "--abi", "none", "--platform", "any",
            "--python-version", MIN_PYTHON,
            "-d", str(CACHE_PURE)])

    selected = [_find_wheel(name, version) for name, version in read_lockfile()]
    for whl in selected:
        unzip_wheel_to_shared(whl)
    _assert_pure()
    return selected

def write_vendor_manifest(wheels: list[Path]):
    """Record exactly what was vendored (name, version, wheel, sha256)."""
    entries = []
    for whl in sorted(wheels, key=lambda p: p.name.lower()):
        name, version = whl.name.split("-")[:2]
        entries.append({
            "name": name,
            "version": version,
            "wheel": whl.name,
            "sha256": hashlib.sha256(whl.read_bytes()).hexdigest(),
        })
    (LIB / "vendor_manifest.json").write_text(
        json.dumps(entries, indent=2) + "\n", encoding="utf-8"
    )

# --- Pack ---------------------------------------------------------------------

def make_zip(version: str):
    # Anki's install-from-file dialog only lists *.ankiaddon (it's a zip inside)
    out = DIST / f"tsunagi-{version}.ankiaddon"
    if out.exists():
        out.unlink()

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # top-level files
        for rel in ["meta.json", "manifest.json", "config.json", "__init__.py", "README.md", "CHANGELOG.md"]:
            p = ROOT / rel
            if p.exists():
                z.write(p, arcname=p.name)

        def include(p: Path) -> bool:
            # Skip stale bytecode from the source tree
            return p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"

        # lib/ (vendored deps)
        for p in LIB.rglob("*"):
            if include(p):
                z.write(p, arcname=str(p.relative_to(ROOT)))

        # your package code
        for p in PKG_ROOT.rglob("*"):
            if include(p):
                z.write(p, arcname=str(p.relative_to(ROOT)))

    print("Built:", out)

# --- Main ---------------------------------------------------------------------

def main():
    args = parse_args()

    # Ensure pip exists
    try:
        sh([sys.executable, "-m", "pip", "--version"])
    except subprocess.CalledProcessError:
        print("pip is required on PATH.", file=sys.stderr)
        sys.exit(2)

    version = read_version()
    print("Version:", version)

    # Prepare caches (persistent) and clean lib/dist (ephemeral)
    prepare_cache(refresh=args.refresh)
    clean_lib_and_dist()

    # 1) Pure-Python deps → lib/shared/
    wheels = vendor_pure_python_deps(offline=args.offline)

    # 2) Record what was vendored
    write_vendor_manifest(wheels)

    # 3) Bump meta.mod
    bump_meta_mod()

    # 4) Build the final .ankiaddon ZIP
    make_zip(version)

if __name__ == "__main__":
    main()
