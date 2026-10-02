"""Tsunagi's log goes to Anki's per-add-on log file too (backlog 5.3)."""
import logging
from types import SimpleNamespace

import pytest

from tsunagi import log as tlog


class Capture(logging.Handler):
    """Stands in for Anki's rotating file."""
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture()
def addon_file(monkeypatch):
    import aqt
    capture = Capture()
    addon = logging.getLogger("addon.test_folder")
    addon.addHandler(capture)
    monkeypatch.setattr(aqt.mw, "addonManager",
                        SimpleNamespace(get_logger=lambda module: addon), raising=False)
    yield capture
    addon.removeHandler(capture)
    for name in ("test_folder", "uvicorn"):
        logging.getLogger(name).removeHandler(capture)
    tlog.log.setLevel(logging.NOTSET)


def test_tsunagi_and_uvicorn_share_the_add_on_log_file(addon_file):
    # What feature.py does at each profile open. Installed, Tsunagi's logger is
    # "<folder>.tsunagi", a child of the add-on's logger.
    from tsunagi._kiso.logs import attach_to_anki
    for _ in range(2):   # a second profile open adds nothing twice
        attach_to_anki("test_folder", logging.getLogger("test_folder"), also=("uvicorn",))
    logging.getLogger("test_folder.tsunagi").warning("from Tsunagi")
    logging.getLogger("uvicorn").warning("from uvicorn")
    assert addon_file.lines == ["from Tsunagi", "from uvicorn"]


def test_log_level_debug_turns_on_tsunagis_debug_lines():
    try:
        tlog.set_level("debug")
        assert tlog.log.level == logging.DEBUG
        tlog.set_level("warning")
        assert tlog.log.level == logging.INFO  # start/stop lines are kept
    finally:
        tlog.log.setLevel(logging.NOTSET)


def test_a_failing_route_is_logged_with_its_traceback(client, monkeypatch, caplog):
    from tsunagi.http.v1 import collection

    def boom():
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(collection, "collection_meta", boom)
    with caplog.at_level(logging.ERROR, logger=tlog.PACKAGE):
        assert client.get("/v1/collection").status_code == 500
    [record] = [r for r in caplog.records if r.name.startswith(tlog.PACKAGE)]
    assert record.getMessage() == "Meta failed" and "disk on fire" in record.exc_text
