#!/usr/bin/env python3
"""
Builds a single .ankiaddon ZIP that vendors:
- Pure-Python deps (FastAPI latest, Pydantic v2, Starlette, AnyIO, h11, uvicorn, packaging) under lib/shared/
- pydantic-core native wheels for multiple platforms/ABIs under:
    lib/<os>/pydantic_core/<py_tag>/<platform_tag>/

Usage:
  python tools/build_addon.py [--refresh] [--offline]

Config:
- PURE_REQS: pure-Python deps to vendor
- CORE_PLATFORMS: just OS + platform tags (no Python versions)
- PY_MINOR_RANGE: Python minors to cover (e.g., 3.9 → 3.13)
- Version is read from tools/version.py (VERSION = "...").
"""

import argparse
import json
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

# Persistent local wheel cache
CACHE = ROOT / ".wheelhouse"
CACHE_PURE = CACHE / "pure"
CACHE_CORE = CACHE / "core"

# --- What to vendor -----------------------------------------------------------

# Pure-Python runtime deps (latest). Keep these pure to avoid per-OS wheels.
PURE_REQS = [
    "fastapi",          # latest
    "pydantic>=2",      # latest v2 (pure wheel)
    "starlette",        # latest
    "anyio",            # latest
    "h11",              # HTTP parser
    "uvicorn==0.30.6",  # pure-Python uvicorn (no [standard])
    "lark",
    "glom",
    "packaging",        # used at runtime to select native pydantic-core
]

# pydantic-core is native; we fetch for each (OS/platform) × (Python minor) combo.

# Declare platforms once (no Python versions here).
# Keys become subfolders under lib/<os_dir>/
CORE_PLATFORMS = {
    # Windows x64
    "win": [
        "win_amd64",
    ],
    # macOS (Intel + Apple Silicon)
    "macos": [
        "macosx_11_0_x86_64",
        "macosx_11_0_arm64",
    ],
    # Linux glibc x86_64 (manylinux2014+)
    "linux": [
        "manylinux_2_17_x86_64",
        # If you want aarch64 later, add: "manylinux_2_17_aarch64",
    ],
}

# Python minors to cover (inclusive): 3.9 → 3.13
PY_MINOR_RANGE = [39, 310, 311, 312, 313]

CORE_PACKAGE = "pydantic-core"

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
    CACHE_CORE.mkdir(parents=True, exist_ok=True)

def read_version() -> str:
    ns = {}
    exec((TOOLS / "version.py").read_text(encoding="utf-8"), ns)
    return ns["VERSION"]

def bump_meta_mod():
    if META.exists():
        data = json.loads(META.read_text(encoding="utf-8"))
        data["mod"] = int(time.time())
        META.write_text(json.dumps(data, indent=2), encoding="utf-8")

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

def extract_core_native(whl: Path, dest_dir: Path):
    with zipfile.ZipFile(whl) as z:
        for n in z.namelist():
            if not n.startswith("pydantic_core") or n.endswith("/"):
                continue
            out_path = dest_dir / n
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(out_path, "wb") as dst:
                dst.write(src.read())

def write_dependencies_txt(core_paths: list[str]):
    lines = []
    lines.append("# Vendored dependencies (auto-generated)\n")
    lines.append("# name".ljust(42) + "path(s)\n")
    # shared (pure) — list top-level packages/modules under lib/shared
    top_entries = sorted({
        p.relative_to(SHARED).parts[0]
        for p in SHARED.glob("*")
        if p.is_dir() or p.suffix == ".py"
    })
    for name in top_entries:
        lines.append(f"{name:<42}shared/{name}")
    # pydantic-core multi-paths
    if core_paths:
        lines.append(f"{CORE_PACKAGE:<42}{core_paths[0]}")
        for p in core_paths[1:]:
            lines.append(" " * 42 + p)
    else:
        lines.append(f"{CORE_PACKAGE:<42}(none)")
    (LIB / "dependencies.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

# --- Cache-aware vendoring ----------------------------------------------------

def vendor_pure_python_deps(offline: bool) -> list[Path]:
    """
    Ensure pure wheels exist in CACHE_PURE (download if not offline),
    then unpack all into lib/shared/.
    """
    if not offline:
        # pip will skip files that already exist in -d dir
        sh([sys.executable, "-m", "pip", "download",
            "--only-binary=:all:", "--prefer-binary",
            "-d", str(CACHE_PURE), *PURE_REQS])
    else:
        if not any(CACHE_PURE.glob("*.whl")):
            raise RuntimeError("offline mode: no cached pure-python wheels in .wheelhouse/pure")

    whls = list(CACHE_PURE.glob("*.whl"))
    if not whls:
        raise RuntimeError("no pure-python wheels available in cache")
    for whl in whls:
        unzip_wheel_to_shared(whl)
    return whls

def _core_cache_dir(os_dir: str, py_tag: str, platform_tag: str) -> Path:
    return CACHE_CORE / f"{os_dir}_{py_tag}_{platform_tag}"

def _py_tags(minor: int) -> tuple[str, str]:
    """
    minor=311 -> ('cp311','311') for --abi and --python-version
    """
    return (f"cp{minor}", f"{minor}")

def vendor_pydantic_core(offline: bool) -> list[str]:
    """
    For each (OS/platform) × (Python minor) combo, ensure a pydantic-core wheel exists
    in cache (download unless offline), then extract into:
        lib/<os>/pydantic_core/<py_tag>/<platform_tag>/

    Returns a flat list of relative paths that were populated (for dependencies.txt).
    """
    out_paths: list[str] = []

    for os_dir, plat_tags in CORE_PLATFORMS.items():
        for minor in PY_MINOR_RANGE:
            py_tag, py_ver_num = _py_tags(minor)
            abi_tag = py_tag  # pydantic-core wheels use cpXY ABIs

            for platform_tag in plat_tags:
                wheels_dir = _core_cache_dir(os_dir, py_tag, platform_tag)
                wheels_dir.mkdir(parents=True, exist_ok=True)

                if not offline and not list(wheels_dir.glob("pydantic_core-*.whl")):
                    cmd = [
                        sys.executable, "-m", "pip", "download",
                        "--only-binary=:all:", "--prefer-binary",
                        "--platform", platform_tag,
                        "--python-version", py_ver_num,
                        "--implementation", "cp",
                        "--abi", abi_tag,
                        "-d", str(wheels_dir),
                        CORE_PACKAGE,
                    ]
                    try:
                        sh(cmd)
                    except subprocess.CalledProcessError:
                        print(f"!! Failed to download {CORE_PACKAGE} for {os_dir} {py_tag} {platform_tag}")
                        continue

                whl_files = list(wheels_dir.glob("pydantic_core-*.whl"))
                if not whl_files:
                    if offline:
                        raise RuntimeError(f"offline mode: missing cached wheel for {os_dir} {py_tag} {platform_tag}")
                    print(f"!! No wheel found for {CORE_PACKAGE} at {wheels_dir}")
                    continue

                whl = whl_files[0]
                dest = LIB / os_dir / "pydantic_core" / py_tag / platform_tag
                extract_core_native(whl, dest)

                rel = dest.relative_to(ROOT).as_posix()
                out_paths.append(rel)

    return out_paths

# --- Pack ---------------------------------------------------------------------

def make_zip(version: str):
    out = DIST / f"tsunagi-{version}.ankiaddon.zip"
    if out.exists():
        out.unlink()

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # top-level files
        for rel in ["meta.json", "manifest.json", "config.json", "__init__.py", "README.md", "CHANGELOG.md"]:
            p = ROOT / rel
            if p.exists():
                z.write(p, arcname=p.name)

        # lib/ (vendored deps)
        for p in LIB.rglob("*"):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(ROOT)))

        # your package code
        for p in PKG_ROOT.rglob("*"):
            if p.is_file():
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
    vendor_pure_python_deps(offline=args.offline)

    # 2) pydantic-core natives → lib/<os>/pydantic_core/<py_tag>/<platform_tag>/
    core_paths = vendor_pydantic_core(offline=args.offline)

    # 3) Write a simple manifest for humans
    write_dependencies_txt(core_paths)

    # 4) Bump meta.mod
    bump_meta_mod()

    # 5) Build the final .ankiaddon ZIP
    make_zip(version)

if __name__ == "__main__":
    main()
