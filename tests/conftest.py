import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Run tests against the exact vendored runtime stack. Build it first:
#   python tools/build_addon.py
_SHARED = ROOT / "lib" / "shared"
if not _SHARED.is_dir():
    raise RuntimeError(
        "lib/shared missing - run `python tools/build_addon.py` before pytest"
    )

for p in (str(_SHARED), str(ROOT), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

# The real Anki library is a test dependency: tests run against the actual
# Rust backend, not a hand-written imitation of it. A fake collection hid four
# return-path bugs across M5 - see the M5c section of the plan.
try:
    import anki.collection  # noqa: F401
except ImportError as exc:  # pragma: no cover - environment guard
    raise RuntimeError(
        "the anki library is missing - tests run against a real collection.\n"
        "  install it with: python -m pip install 'anki==23.10'\n"
        "(23.10 is our declared floor; CI also runs the latest release)"
    ) from exc

# aqt calls this during startup; pylib on its own leaves anki.lang.current_i18n
# as None, and anything routed through the Rust backend's text helpers -
# anki.utils.field_checksum / strip_html_media, which the AnkiConnect duplicate
# check uses - raises AttributeError without it. Inside Anki this is already
# done for us, so it belongs in the harness rather than in tsunagi.
import anki.lang  # noqa: E402

anki.lang.set_lang("en_US")

# Install fake aqt modules BEFORE any test module imports tsunagi's
# Anki-facing code (conftest execution precedes test-module collection).
# Only aqt is stubbed - it drags in Qt, and its threading is what we want to
# short-circuit. `anki` above is the genuine package.
from fakes.anki_stubs import install, mw  # noqa: E402

install()


@pytest.fixture()
def col(tmp_path):
    """A real, empty Anki collection assigned to the fake mw.col."""
    from anki.collection import Collection

    mw.col = Collection(str(tmp_path / "collection.anki2"))
    try:
        yield mw.col
    finally:
        mw.col.close()
        mw.col = None


@pytest.fixture()
def reset_settings():
    """Pin the live settings singleton to defaults for the test's duration."""
    from tsunagi.adapters.config import DEFAULTS
    from tsunagi.adapters.settings import settings

    settings.configure(dict(DEFAULTS), persist=None)
    yield settings
    settings.configure(dict(DEFAULTS), persist=None)


@pytest.fixture()
def client(col, reset_settings):
    """TestClient over the real full app (auth off, no Origin header sent)."""
    from fastapi.testclient import TestClient

    from tsunagi.app import app

    with TestClient(app) as c:
        yield c
