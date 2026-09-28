"""
Tsunagi's log (backlog 5.3). Records from Tsunagi's modules and from uvicorn
also go to Anki's per-add-on log file, logs/addons/<folder>/<folder>.log
(Tools > Add-ons > View Files shows the folder's parent), which rotates daily
and keeps ten days. The console still gets them through Anki's root logger.

Anki gives a log file only to loggers named "addon.<folder>", and gives every
child of that name its own file handler; so Tsunagi's loggers share that one
handler instead of living under the prefix, which would repeat each line.
"""
from __future__ import annotations

import logging

# The inner package: "<add-on folder>.tsunagi" when installed, "tsunagi" in tests.
PACKAGE = __name__.rsplit(".", 1)[0]
log = logging.getLogger(PACKAGE)


def attach_to_anki(addon_module: str, log_level: str) -> None:
    """Share the add-on log file with Tsunagi's and uvicorn's loggers. Tsunagi
    logs at INFO, or DEBUG with log_level "debug"; uvicorn's own level
    follows log_level where the server starts it."""
    from aqt import mw
    addon_logger = mw.addonManager.get_logger(addon_module)
    for name in (PACKAGE, "uvicorn"):
        target = logging.getLogger(name)
        for handler in addon_logger.handlers:
            if handler not in target.handlers:
                target.addHandler(handler)
    log.setLevel(logging.DEBUG if str(log_level).lower() == "debug" else logging.INFO)
