"""Real-Anki checks on Kiso's harness (kiso_dev.harness): Anki runs offscreen in
a throwaway profile, with Tsunagi installed through its real root __init__.py,
so its server, hooks and settings are the ones a user gets.

    from qt_smoke import aqt, run, tsunagi, until

    def check(app, screenshot):            # screenshot: a .png path, or None
        gui = tsunagi("adapters.anki.gui")  # the installed add-on's module
        ...

    if __name__ == "__main__":
        run(check, __doc__)                 # --screenshots DIR saves <check>.png there
"""

# isort: off
# kiso_dev.harness sets Qt up for offscreen use before aqt loads, so it comes first.
from kiso_dev import harness
from kiso_dev.harness import addon, js, pump, until  # noqa: F401  (re-exported for the checks)

import importlib
import sys
from pathlib import Path

import aqt  # noqa: F401  (re-exported for the checks)
# isort: on


def tsunagi(module: str):
    """A module of the installed add-on's package: tsunagi("adapters.anki.gui")."""
    return importlib.import_module(f"{addon().__name__}.tsunagi.{module}")


def wait_for_editor(app, editor):
    """Wait for the editor's asynchronous JavaScript save bridge."""

    def ready():
        result = []
        editor.web.page().runJavaScript("typeof saveNow === 'function'", result.append)
        until(app, lambda: bool(result))
        return result[0]

    until(app, ready)


def run(check, description):
    """Run check(app, screenshot) in Anki once it shows the deck list."""
    name = Path(sys.argv[0]).stem
    harness.run(lambda app, shots, base: check(app, shots / f"{name}.png" if shots else None),
                description)
