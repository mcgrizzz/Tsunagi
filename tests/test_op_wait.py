"""Cross-thread waits: the default deadline, and FOREVER for long work (7.7a)."""
import threading

import pytest

from tsunagi.adapters import ops
from tsunagi.shared.errors import AnkiBusyError


def later(seconds):
    done = threading.Event()
    threading.Timer(seconds, done.set).start()
    return done


def test_default_deadline_is_op_timeout(monkeypatch):
    monkeypatch.setattr(ops, "OP_TIMEOUT", 0.05)
    with pytest.raises(AnkiBusyError, match="Sync timed out"):
        ops._wait(later(0.5), {}, None, "Sync")


def test_forever_outlasts_op_timeout(monkeypatch):
    # A sync longer than op_timeout_seconds used to answer 503 while it ran on.
    monkeypatch.setattr(ops, "OP_TIMEOUT", 0.05)
    assert ops._wait(later(0.3), {"result": "synced"}, ops.FOREVER, "Sync") == "synced"
