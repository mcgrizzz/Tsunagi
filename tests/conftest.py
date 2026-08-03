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

# Install fake aqt/anki modules BEFORE any test module imports tsunagi's
# Anki-facing code (conftest execution precedes test-module collection).
# The real aqt/anki are never installed in the test env, so this cannot
# shadow anything for the aqt-free tests.
from fakes.anki_stubs import install, mw  # noqa: E402

install()


@pytest.fixture()
def fake_col():
    """Fresh seeded FakeCollection assigned to the fake mw.col."""
    from fakes.collection import FakeCollection

    mw.col = FakeCollection()
    yield mw.col
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
def client(fake_col, reset_settings):
    """TestClient over the real full app (auth off, no Origin header sent)."""
    from fastapi.testclient import TestClient

    from tsunagi.app import app

    with TestClient(app) as c:
        yield c
