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


def test_the_clients_share_the_api_version():
    # A client's major.minor is the add-on's (the API it speaks); its patch is
    # its own, so a client-only change ships without an add-on release.
    import json

    typescript = Path(__file__).resolve().parents[1] / "packages" / "typescript"
    package = json.loads((typescript / "package.json").read_text(encoding="utf-8"))["version"]
    lock = json.loads((typescript / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == lock["packages"][""]["version"] == package
    assert package.split(".")[:2] == ADDON_VERSION.split(".")[:2], (package, ADDON_VERSION)
