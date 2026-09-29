"""
Qt dialogs for the permission flow, and the AnkiConnect takeover helpers.
All aqt imports are function-local so this module stays importable headless.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event
from typing import Any

from .config import with_default_app_key

ANKICONNECT_ID = "2055492159"


@dataclass(frozen=True)
class PermissionDecision:
    accepted: bool = False
    ignore: bool = False

    def __bool__(self) -> bool:
        return self.accepted


def ask_permission_dialog(origin: Any, *, timeout: float = 120.0) -> PermissionDecision:
    """
    Blocking Yes/No prompt on the Qt main thread.
    Returns the choice and whether a denied request should be ignored later.
    """
    from aqt import mw
    from aqt.qt import QCheckBox, QMessageBox, Qt

    from ..shared.errors import AnkiBusyError
    from .ops import call_on_main

    cancelled = Event()
    active_dialog = None  # Read and written only on the UI thread.

    def close_expired_dialog() -> None:
        if active_dialog is not None:
            active_dialog.reject()

    def _ask() -> PermissionDecision:
        nonlocal active_dialog
        # The UI callback may still be queued when the HTTP waiter expires.
        if cancelled.is_set():
            return PermissionDecision()
        msg = QMessageBox(None)
        msg.setWindowTitle("Tsunagi")
        msg.setText(f'Allow "{origin}" to access Anki through Tsunagi?')
        msg.setInformativeText(
            "Granting access allows this website to modify your collection, "
            "including deleting decks and notes."
        )
        msg.setWindowIcon(mw.windowIcon())
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.setCheckBox(QCheckBox(text=f'Ignore further requests from "{origin}"', parent=msg))
        if hasattr(Qt, "WindowStaysOnTopHint"):
            msg.setWindowFlags(Qt.WindowStaysOnTopHint)
        else:
            msg.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        if cancelled.is_set():
            return PermissionDecision()
        active_dialog = msg
        try:
            pressed = msg.exec()
        finally:
            active_dialog = None
        if cancelled.is_set():
            return PermissionDecision()
        return PermissionDecision(
            accepted=pressed == QMessageBox.StandardButton.Yes,
            ignore=pressed == QMessageBox.StandardButton.No and msg.checkBox().isChecked(),
        )

    try:
        return call_on_main(_ask, timeout=timeout)
    except AnkiBusyError:
        cancelled.set()
        # Qt's modal loop processes queued callbacks. Close on that thread;
        # never touch a widget from the HTTP worker or wait on it again here.
        mw.taskman.run_on_main(close_expired_dialog)
        return PermissionDecision()


def offer_ankiconnect_import() -> None:
    """
    One-time offer to take over from AnkiConnect: opens the settings page with
    its takeover dialog (the same one as the Server page's button). Called on
    profile_did_open (main thread), after start_server.

    Flag semantics: ankiconnect_import_offered is set as soon as the offer is
    shown, whatever the answer, but NOT when AnkiConnect isn't installed - so
    users who install AnkiConnect later still get the offer.
    """
    from aqt import mw

    from .settings import settings
    from .settings_page import open_settings

    if settings.get("ankiconnect_import_offered"):
        return
    if mw.addonManager.getConfig(ANKICONNECT_ID) is None:
        return
    settings.update(ankiconnect_import_offered=True)
    open_settings(mw, offer_takeover=True)


def ankiconnect_import_record() -> dict:
    """Metadata saved with an accepted import, never when merely previewing it."""
    return {
        "ankiconnect_import_offered": True,
        "ankiconnect_imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def ankiconnect_status(manager: Any) -> dict:
    """Inspect installation and saved enabled state without changing either."""
    installed = ANKICONNECT_ID in manager.allAddons()
    return {
        "installed": installed,
        "enabled": bool(manager.addon_meta(ANKICONNECT_ID).enabled) if installed else False,
        "config_available": manager.getConfig(ANKICONNECT_ID) is not None if installed else False,
    }


def ankiconnect_import_changes(cfg: dict, ac: dict, *, include_port: bool = False) -> dict:
    """Share key/origin merging; port takeover is explicit in settings only."""
    changes: dict = {"ankiconnect_import_offered": True}
    if ac.get("apiKey"):
        changes["apps"] = with_default_app_key(cfg, ac["apiKey"])
    merged = list(cfg.get("cors_allowlist", []))
    for origin in ac.get("webCorsOriginList") or []:
        if origin not in merged:
            merged.append(origin)
    changes["cors_allowlist"] = merged
    if include_port:
        port = ac.get("webBindPort")
        if port is not None:
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("AnkiConnect's port must be an integer between 1 and 65535.")
            changes["port"] = port
            changes["prefer_port"] = port
        changes["enabled"] = True
    return changes



def stop_ankiconnect_server():
    """Stop the loaded standard addon on the Qt thread; return a rollback callback."""
    import sys

    module = sys.modules.get(ANKICONNECT_ID)
    if module is None:
        return None
    instance = getattr(module, "ac", None)
    server = getattr(instance, "server", None)
    timer = getattr(instance, "timer", None)
    if (server is None or not hasattr(server, "sock")
            or not callable(getattr(server, "close", None))
            or not callable(getattr(server, "listen", None))):
        raise RuntimeError("This AnkiConnect version cannot hand over its running server. "
                           "Disable it and restart Anki before importing.")
    if timer is not None and not all(callable(getattr(timer, name, None))
                                     for name in ("stop", "start", "interval", "isActive")):
        raise RuntimeError("This AnkiConnect timer cannot be stopped safely. Restart Anki first.")
    was_listening = server.sock is not None
    was_active = timer is not None and timer.isActive()
    interval = timer.interval() if timer is not None else 0

    def restore():
        if was_listening:
            server.listen()
        if was_active:
            timer.start(interval)

    try:
        if timer is not None:
            timer.stop()
        server.close()
    except Exception:
        restore()
        raise
    return restore
