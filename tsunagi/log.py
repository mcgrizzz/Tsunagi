"""
Tsunagi's log (backlog 5.3). Records from Tsunagi's modules and from uvicorn
also go to Anki's per-add-on log file, logs/addons/<folder>/<folder>.log
(Tools > Add-ons > View Files shows the folder's parent), which rotates daily
and keeps ten days. The console still gets them through Anki's root logger.

Kiso attaches the file to the add-on's logger, named after its folder
(feature.py); Tsunagi's logger is its child, so its records reach the file
through it, once.
"""
from __future__ import annotations

import logging

# The inner package: "<add-on folder>.tsunagi" when installed, "tsunagi" in tests.
PACKAGE = __name__.rsplit(".", 1)[0]
log = logging.getLogger(PACKAGE)


def set_level(log_level: str) -> None:
    """Tsunagi logs at INFO, or DEBUG with log_level "debug"; uvicorn's own
    level follows log_level where the server starts it."""
    log.setLevel(logging.DEBUG if str(log_level).lower() == "debug" else logging.INFO)
