"""Exercise the release artifact without network access or a live Anki profile."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "build_addon.py"


@pytest.fixture
def builder(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("build_addon_under_test", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, relative in (
        ("ROOT", "."), ("LIB", "lib"), ("SHARED", "lib/shared"),
        ("PKG_ROOT", "tsunagi"), ("DIST", "dist"),
    ):
        monkeypatch.setattr(module, name, tmp_path / relative)
    files = {
        "__init__.py": "# entry point\n",
        "tsunagi/__init__.py": "",
        "tsunagi/static/reference.js": "// runtime asset\n",
        "manifest.json": json.dumps({"package": "tsunagi", "name": "Tsunagi"}),
        "config.json": "{}",
        "config.md": "Settings",
        "LICENSE": "Project license",
        "lib/vendor_manifest.json": "[]",
        "lib/shared/example.py": "# dependency\n",
        "meta.json": '{"config": {"api_key": "private"}}',
        "docs/routing_efficiency_handoff.md": "private handoff",
        "tests/example.py": "# test only",
        "tsunagi/__pycache__/cached.pyc": "bytecode",
        "lib/shared/old.pyo": "bytecode",
        "tsunagi/.env": "private",
        "tsunagi/debug.log": "log",
        "tsunagi/editor.py~": "backup",
    }
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return module


def test_release_layout_contents_checksum_and_repeatability(builder):
    out = builder.make_zip("1.2.3")
    original = out.read_bytes()
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {
            "__init__.py", "tsunagi/__init__.py", "tsunagi/static/reference.js",
            "manifest.json", "config.json", "config.md", "LICENSE",
            "lib/vendor_manifest.json", "lib/shared/example.py",
        }
    assert out.with_suffix(".ankiaddon.sha256").read_text().strip() == (
        f"{hashlib.sha256(original).hexdigest()}  {out.name}"
    )
    builder.make_zip("1.2.3")
    assert out.read_bytes() == original
    assert "private" in (builder.ROOT / "meta.json").read_text()


@pytest.mark.parametrize("broken", ["__init__.py", "lib/shared/example.py", "config.json"])
def test_failed_build_preserves_previous_release(builder, broken):
    out = builder.make_zip("1.2.3")
    original = out.read_bytes()
    checksum = out.with_suffix(".ankiaddon.sha256").read_bytes()
    (builder.ROOT / broken).unlink()
    with pytest.raises(RuntimeError):
        builder.make_zip("1.2.3")
    assert out.read_bytes() == original
    assert out.with_suffix(".ankiaddon.sha256").read_bytes() == checksum
    assert not list(builder.DIST.glob(".tsunagi-build-*"))


def test_wheel_license_notices_survive_vendoring(builder):
    wheel = builder.ROOT / "example-1.0-py3-none-any.whl"
    licenses = {
        "example-1.0.dist-info/LICENSE": "Old-style license",
        "example-1.0.dist-info/licenses/third-party.txt": "Third party license",
        "example-1.0.dist-info/NOTICE.txt": "Notice",
    }
    with zipfile.ZipFile(wheel, "w") as z:
        for name, content in licenses.items():
            z.writestr(name, content)
        z.writestr("example-1.0.dist-info/METADATA", "Package metadata")
        z.writestr("example.py", "# runtime\n")
    builder.unzip_wheel_to_shared(wheel)
    with zipfile.ZipFile(builder.make_zip("1.0")) as z:
        for name, content in licenses.items():
            assert z.read("lib/shared/" + name).decode() == content


def test_refresh_offline_rejected_before_cache_deletion():
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--refresh", "--offline"],
        text=True, capture_output=True,
    )
    assert result.returncode == 2
    assert "cannot be combined" in result.stderr
