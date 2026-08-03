#!/usr/bin/env python3
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional

# --- Paths --------------------------------------------------------------------

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
DIST = ROOT / "dist"

# Windows Anki paths
ANKI_ADDON_DIR = Path(r"C:\Users\Andrew\AppData\Roaming\Anki2\addons21\tsunagi")
ANKI_CONSOLE_EXE = Path(r"C:\Users\Andrew\AppData\Local\Programs\Anki\anki-console.bat")

# --- Helpers ------------------------------------------------------------------

def sh(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=check)

def kill_process(image_name: str) -> None:
    """Silently kill a process by name if running (Windows)."""
    try:
        subprocess.run(["taskkill", "/IM", image_name, "/F", "/T"], check=False, capture_output=True)
    except Exception as e:
        print(f"Ignored taskkill error: {e}")

def latest_zip(dist_dir: Path) -> Optional[Path]:
    """Return the newest built add-on (a zip under an .ankiaddon name)."""
    zips = sorted(dist_dir.glob("*.ankiaddon"), key=lambda p: p.stat().st_mtime, reverse=True)
    return zips[0] if zips else None

def extract_zip(src: Path, dest: Path) -> None:
    """Wipe destination and extract ZIP there."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        z.extractall(dest)

# --- Main ---------------------------------------------------------------------

def main() -> int:
    print("== Step 1: Building add-on ==")
    try:
        sh([sys.executable, str(TOOLS / "build_addon.py")])
    except subprocess.CalledProcessError:
        print("Build failed.")
        return 1

    print("== Step 2: Closing Anki (if open) ==")
    kill_process("anki.exe")

    print("== Step 3: Installing built add-on ==")
    zip_path = latest_zip(DIST)
    if not zip_path:
        print(f"No build found in {DIST}")
        return 2
    print(f"Using build: {zip_path.name}")
    extract_zip(zip_path, ANKI_ADDON_DIR)

    print("== Step 4: Opening Anki Console ==")
    if not ANKI_CONSOLE_EXE.exists():
        print(f"anki-console.exe not found at: {ANKI_CONSOLE_EXE}")
        return 3
    subprocess.Popen([str(ANKI_CONSOLE_EXE)], close_fds=True)

    print("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
