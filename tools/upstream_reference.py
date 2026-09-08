"""Load a pinned AnkiConnect reference without starting its server or Qt UI.

Requires Python 3.12 and jsonschema 4.23.0 to load the upstream source. Action implementations,
decorators, helpers and response formatting come from the checkout unchanged.
Only host integration (collection access, edit notifications and logging) is
replaced by the caller. The HTTP wrapper can run without opening a socket; this
does not test socket transport or GUI behavior.
"""

import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from types import ModuleType

UPSTREAM_REVISION = "de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e"


@dataclass
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes

    def json(self):
        return json.loads(self.content)


def load_reference(checkout):
    if sys.version_info < (3, 12):
        raise RuntimeError("The pinned upstream source requires Python 3.12 or newer")
    checkout = Path(checkout).resolve()
    revision = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True,
    ).strip()
    if revision != UPSTREAM_REVISION:
        raise RuntimeError(f"Expected upstream {UPSTREAM_REVISION}, got {revision}")
    subprocess.run(
        ["git", "-C", str(checkout), "diff", "--exit-code", "HEAD", "--", "plugin"],
        check=True, stdout=subprocess.DEVNULL,
    )

    def execute(path, namespace, keep):
        filename = checkout / path
        tree = ast.parse(filename.read_text(encoding="utf-8"), filename=str(filename))
        tree.body = [node for node in tree.body if keep(node)]
        exec(compile(tree, str(filename), "exec"), namespace)

    util = ModuleType("upstream_reference_util")
    execute("plugin/util.py", util.__dict__, lambda node: True)
    # Defaults match an unconfigured upstream addon.
    util.setting = lambda key: util.DEFAULT_CONFIG[key]
    parts = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", version("anki")).groups()
    namespace = {
        "__name__": "upstream_reference", "util": util,
        "anki_version": tuple(int(part or 0) for part in parts),
    }
    execute("plugin/web.py", namespace, lambda node: isinstance(
        node, (ast.FunctionDef, ast.ClassDef, ast.Assign, ast.Import)))

    def keep_main(node):
        if isinstance(node, ast.ClassDef):
            return node.name == "AnkiConnect"
        if isinstance(node, ast.Import):
            return True
        return isinstance(node, ast.ImportFrom) and node.level == 0 and node.module != "aqt.qt"

    execute("plugin/__init__.py", namespace, keep_main)
    reference = namespace["AnkiConnect"].__new__(namespace["AnkiConnect"])
    reference.log = None
    reference.startEditing = lambda: None
    reference.stopEditing = lambda: None
    server = namespace["WebServer"](reference.handler)

    def http_raw_request(content, *, headers=None, method="POST"):
        request = namespace["WebRequest"](
            method.encode("ascii"),
            {key.lower().encode("ascii"): value.encode("utf-8")
             for key, value in (headers or {}).items()},
            content,
        )
        response = server.handlerWrapper(request)
        head, body = response.split(b"\r\n\r\n", 1)
        status, *header_lines = head.decode("utf-8").split("\r\n")
        response_headers = {}
        for line in header_lines:
            key, value = line.split(":", 1)
            response_headers[key.lower()] = value.strip()
        return HttpResponse(int(status.split()[1]), response_headers, body)

    def http_request(payload):
        return http_raw_request(json.dumps(payload).encode()).json()

    reference.http_request = http_request
    reference.http_raw_request = http_raw_request
    reference.request_schema = namespace["request_schema"]
    return reference


def signature_manifest(reference):
    """Snapshot public argument names and aliases from the pinned reference."""
    import inspect
    import json

    manifest = {}
    for name, method in inspect.getmembers(reference, predicate=inspect.ismethod):
        if not getattr(method, "api", False):
            continue
        required, optional = [], []
        variadic = False
        for parameter in inspect.signature(method).parameters.values():
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                variadic = True
            else:
                assert parameter.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
                target = required if parameter.default is inspect.Parameter.empty else optional
                target.append(parameter.name)
        manifest[name] = [required, optional, variadic, list(getattr(method, "versions", []))]
    return json.loads(json.dumps(manifest))
