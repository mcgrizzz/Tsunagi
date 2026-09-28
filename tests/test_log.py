"""Tsunagi's log goes to Anki's per-add-on log file too (backlog 5.3)."""
import logging
from types import SimpleNamespace

import pytest

from tsunagi import log as tlog


@pytest.fixture()
def addon_logger(monkeypatch):
    import aqt
    file_handler = logging.NullHandler()   # stands in for Anki's rotating file
    addon = logging.getLogger("addon.test_folder")
    addon.addHandler(file_handler)
    monkeypatch.setattr(aqt.mw, "addonManager",
                        SimpleNamespace(get_logger=lambda module: addon), raising=False)
    yield file_handler
    addon.removeHandler(file_handler)
    for name in (tlog.PACKAGE, "uvicorn"):
        logging.getLogger(name).removeHandler(file_handler)
    tlog.log.setLevel(logging.NOTSET)


def test_tsunagi_and_uvicorn_share_the_add_on_log_file(addon_logger):
    tlog.attach_to_anki("test_folder", "warning")
    tlog.attach_to_anki("test_folder", "warning")  # a second profile open adds nothing twice
    for name in (tlog.PACKAGE, "uvicorn"):
        assert logging.getLogger(name).handlers.count(addon_logger) == 1
    assert tlog.log.level == logging.INFO  # start/stop lines are kept


def test_debug_log_level_turns_on_tsunagis_debug_lines(addon_logger):
    tlog.attach_to_anki("test_folder", "debug")
    assert tlog.log.level == logging.DEBUG


def test_a_failing_route_is_logged_with_its_traceback(client, monkeypatch, caplog):
    from tsunagi.http.v1 import collection

    def boom():
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(collection, "collection_meta", boom)
    with caplog.at_level(logging.ERROR, logger=tlog.PACKAGE):
        assert client.get("/v1/collection").status_code == 500
    [record] = [r for r in caplog.records if r.name.startswith(tlog.PACKAGE)]
    assert record.getMessage() == "Meta failed" and "disk on fire" in record.exc_text
