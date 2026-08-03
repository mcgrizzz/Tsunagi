import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Run tests against the exact vendored runtime stack. Build it first:
#   python tools/build_addon.py
_SHARED = ROOT / "lib" / "shared"
if not _SHARED.is_dir():
    raise RuntimeError(
        "lib/shared missing - run `python tools/build_addon.py` before pytest"
    )

for p in (str(_SHARED), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)
