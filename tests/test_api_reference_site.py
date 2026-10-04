"""The public API reference (tools/build_api_reference.py) is the local
reference page, read-only, over the API description: it fails here, not in
the release's Pages job, when the page or the description changes under it."""
import importlib.util
import json
from pathlib import Path

from tsunagi.http.playground import SCALAR_SCRIPT_URL

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests/snapshots/openapi.json"


def _builder():
    spec = importlib.util.spec_from_file_location("build_api_reference", ROOT / "tools/build_api_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_site_is_the_description_read_only(tmp_path):
    _builder().build(SNAPSHOT, "9.9.9", tmp_path)
    published = json.loads((tmp_path / "openapi.json").read_text(encoding="utf-8"))
    original = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert published["paths"] == original["paths"]
    assert published["components"] == original["components"]
    assert published["info"]["version"] == "9.9.9"
    assert published["servers"] == [{"url": "http://127.0.0.1:7777", "description": "Tsunagi on this computer"}]
    intro = published["info"]["description"]
    assert intro.startswith("> **Tsunagi 9.9.9, read-only.**") and "](/" not in intro

    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert SCALAR_SCRIPT_URL in page
    assert "url: 'openapi.json'," in page and "hideTestRequestButton: true," in page
    assert 'href="/' not in page
