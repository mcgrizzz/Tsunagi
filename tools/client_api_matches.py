"""A client patch release may use only what a released add-on serves: the API
description it was built from must match that release's, apart from wording.
The client publish workflow runs it for client-v* tags, with the newest add-on
release of the same major.minor:

    python tools/client_api_matches.py v0.6.0
"""
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


def matches(released: dict, current: dict) -> bool:
    return shape({**released, "info": None}) == shape({**current, "info": None})


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
