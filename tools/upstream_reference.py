"""Load a pinned AnkiConnect reference without starting its server or Qt UI.

Requires Python 3.12 to parse the upstream source. Action implementations,
decorators, helpers and response formatting come from the checkout unchanged.
Only host integration (collection access, edit notifications and logging) is
replaced by the caller. This does not test upstream HTTP transport or GUI behavior.
"""

import ast
import re
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path
from types import ModuleType

UPSTREAM_REVISION = "de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e"


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
    # Defaults match an unconfigured upstream addon. No permission/key tests here.
    util.setting = lambda key: util.DEFAULT_CONFIG[key]
    parts = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", version("anki")).groups()
    namespace = {
        "__name__": "upstream_reference", "util": util,
        "anki_version": tuple(int(part or 0) for part in parts),
    }
    execute("plugin/web.py", namespace, lambda node: isinstance(node, ast.FunctionDef)
            and node.name in {"format_exception_reply", "format_success_reply"})

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
    return reference
