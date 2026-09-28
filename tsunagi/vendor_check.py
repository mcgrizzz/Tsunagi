"""
Another add-on's copy of the libraries Tsunagi bundles (backlog 8.3a).

Tsunagi puts lib/shared first on sys.path, but sys.modules wins: a library
another add-on imported first stays in use for the whole session. For most
libraries that is harmless. For the web stack it is not: FastAPI built against
a different pydantic or starlette fails to start with a traceback. So when
one of those is already loaded at a different version than Tsunagi bundles,
Tsunagi does not start and says which add-on to disable instead.

Standard library only: this runs before any of the stack is imported.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, NamedTuple, Optional

# The server cannot run on another version of these.
CRITICAL = ("fastapi", "starlette", "pydantic", "uvicorn")


class Clash(NamedTuple):
    name: str
    file: str
    version: Optional[str]   # what is loaded, if it says
    bundled: Optional[str]   # what Tsunagi ships

    @property
    def blocks(self) -> bool:
        return self.name in CRITICAL and self.version != self.bundled


def bundled_versions(shared: Path) -> Dict[str, str]:
    """{package: version} from the .dist-info folders in lib/shared."""
    out = {}
    for entry in shared.glob("*.dist-info"):
        name, _, version = entry.name[:-len(".dist-info")].partition("-")
        out[name.lower().replace("-", "_")] = version
    return out


def _version(module: Any) -> Optional[str]:
    for attr in ("__version__", "VERSION"):
        value = getattr(module, attr, None)
        if value is not None:
            return str(value)
    return None


def find_clashes(shared: Path, anki_roots: Iterable[str],
                 modules: Optional[Dict[str, Any]] = None) -> List[Clash]:
    """Bundled packages already imported from outside lib/shared and outside
    Anki's own bundle (which ships some of the same, and is the normal,
    working environment)."""
    modules = sys.modules if modules is None else modules
    prefix, roots = str(shared), tuple(anki_roots)
    versions = bundled_versions(shared)
    out = []
    for child in sorted(shared.iterdir()):
        name = child.name[:-3] if child.name.endswith(".py") else child.name
        if not name.isidentifier():
            continue
        module = modules.get(name)
        file = getattr(module, "__file__", None) if module is not None else None
        if file and not file.startswith(prefix) and not file.startswith(roots):
            out.append(Clash(name, file, _version(module), versions.get(name)))
    return out


def addon_folder(file: str, addons_root: str) -> Optional[str]:
    """The add-on folder a module file lives in, if it is under addons21."""
    try:
        relative = Path(file).resolve().relative_to(Path(addons_root).resolve())
    except ValueError:
        return None
    return relative.parts[0] if relative.parts else None


def refusal(blocking: List[Clash], addon_name: Any) -> str:
    """What to tell the user; `addon_name(file)` names the add-on a file is in."""
    parts = []
    for clash in blocking:
        owner = addon_name(clash.file)
        where = f"the add-on “{owner}”" if owner else clash.file
        loaded = f"version {clash.version}" if clash.version else "another version"
        parts.append(f"{clash.name} ({loaded}, from {where}; Tsunagi needs {clash.bundled})")
    return ("Tsunagi did not start: another add-on loaded a different version of a "
            "library Tsunagi needs: " + "; ".join(parts) + ". Disable that add-on, "
            "or update it or Tsunagi, then restart Anki.")
