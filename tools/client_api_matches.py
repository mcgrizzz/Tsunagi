"""A client patch release may use only what a released add-on serves: the API
description it was built from must match that release's, apart from wording.
The client publish workflow runs it for client-v* tags, with the newest add-on
release of the same major.minor:

    python tools/client_api_matches.py v0.6.0
"""
import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = "tests/snapshots/openapi.json"
PROSE = ("description", "summary")


def shape(node: Any) -> Any:
    """The description without its prose: what a client can depend on."""
    if isinstance(node, dict):
        return {key: shape(value) for key, value in node.items() if key not in PROSE}
    if isinstance(node, list):
        return [shape(value) for value in node]
    return node


def unversioned(description: dict) -> dict:
    """Without what every release changes: `info` and the add-on version that
    Versions.addon defaults to."""
    description = copy.deepcopy({**description, "info": None})
    versions = description.get("components", {}).get("schemas", {}).get("Versions", {})
    versions.get("properties", {}).get("addon", {}).pop("default", None)
    return description


def matches(released: dict, current: dict) -> bool:
    return shape(unversioned(released)) == shape(unversioned(current))


def main(tag: str) -> int:
    shown = subprocess.run(["git", "show", f"{tag}:{SNAPSHOT}"], cwd=ROOT, check=True,
                           capture_output=True, text=True, encoding="utf-8")
    released = json.loads(shown.stdout)
    current = json.loads((ROOT / SNAPSHOT).read_text(encoding="utf-8"))
    if not matches(released, current):
        print(f"The API description differs from {tag}'s beyond its wording: "
              "this client needs an add-on release.", file=sys.stderr)
        return 1
    print(f"The API description matches {tag}'s, apart from wording.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
