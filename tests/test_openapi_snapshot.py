"""The published API contract; any change to it shows as a diff in review.

After an intended change, regenerate the snapshot and commit it:
    TSUNAGI_UPDATE_OPENAPI=1 python -m pytest -q tests/test_openapi_snapshot.py
"""

import difflib
import json
import os
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "snapshots" / "openapi.json"


def test_openapi_matches_snapshot(client):
    schema = client.get("/openapi.json").json()
    schema["info"].pop("version")  # a release bump is not a contract change
    current = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("TSUNAGI_UPDATE_OPENAPI") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(current, encoding="utf-8", newline="\n")
    expected = SNAPSHOT.read_text(encoding="utf-8")
    if current != expected:
        diff = difflib.unified_diff(expected.splitlines(), current.splitlines(),
                                    "snapshot", "current", lineterm="", n=2)
        shown = "\n".join(list(diff)[:60])
        raise AssertionError(
            "The OpenAPI schema changed. If intended, regenerate with "
            "TSUNAGI_UPDATE_OPENAPI=1 (see this file's docstring).\n" + shown)
