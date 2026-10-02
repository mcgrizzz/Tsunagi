"""
reload_addon runs every module again. Pydantic 1 refuses a validator it has
already registered unless it allows reuse, and a schema module that fails to
import leaves the server down (found 2026-10-01 on the owner's reload).
Reloads run in a subprocess so this process keeps its own classes.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

RELOAD = """
import importlib, pkgutil
import tsunagi.shared.schemas as schemas
for info in pkgutil.iter_modules(schemas.__path__):
    importlib.reload(importlib.import_module(f"tsunagi.shared.schemas.{info.name}"))
"""


def test_schema_modules_survive_a_reload():
    # The vendored libraries (lib/shared) are on this process's path only.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    done = subprocess.run([sys.executable, "-c", RELOAD], cwd=REPO, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
