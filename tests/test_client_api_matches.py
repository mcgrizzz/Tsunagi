"""A client patch release needs the same API as a released add-on, apart from
wording (tools/client_api_matches.py, run by the client publish workflow)."""
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("client_api_matches", ROOT / "tools/client_api_matches.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wording_may_change_the_api_may_not():
    tool = _tool()
    released = json.loads((ROOT / "tests/snapshots/openapi.json").read_text(encoding="utf-8"))
    reworded = copy.deepcopy(released)
    reworded["info"]["description"] = "Other words."
    reworded["components"]["schemas"]["CardRow"]["properties"]["due"]["description"] = "Other words."
    assert tool.matches(released, reworded)

    new_field = copy.deepcopy(released)
    new_field["components"]["schemas"]["CardRow"]["properties"]["extra"] = {"type": "integer"}
    assert not tool.matches(released, new_field)

    new_path = copy.deepcopy(released)
    new_path["paths"]["/v1/new"] = {"get": {"responses": {}}}
    assert not tool.matches(released, new_path)
