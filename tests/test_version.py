"""One version: pyproject.toml's (what `kiso build` names the archive and a
release tag must match) is the one Tsunagi reports at run time."""
import sys
from pathlib import Path

from tsunagi.shared.version import ADDON_VERSION

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def test_the_reported_version_is_the_projects():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert ADDON_VERSION == pyproject["project"]["version"]


def test_the_clients_carry_the_same_version():
    # Each client in packages/ is released with the add-on it was tested against.
    import json

    root = Path(__file__).resolve().parents[1] / "packages"
    typescript = root / "typescript"
    for manifest in ("package.json", "package-lock.json"):
        data = json.loads((typescript / manifest).read_text(encoding="utf-8"))
        assert data["version"] == ADDON_VERSION, manifest
    lock = json.loads((typescript / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"][""]["version"] == ADDON_VERSION
