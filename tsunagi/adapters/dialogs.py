"""
Qt dialogs for access requests (AnkiConnect's requestPermission and 6.124's),
and the AnkiConnect takeover helpers.
All aqt imports are function-local so this module stays importable headless.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from threading import Event
from typing import Any, Callable, Tuple

from .config import with_default_app_key

ANKICONNECT_ID = "2055492159"


@dataclass(frozen=True)
class PermissionDecision:
    accepted: bool = False
    ignore: bool = False

    def __bool__(self) -> bool:
        return self.accepted


def _ask_on_main(build: Callable[[], Tuple[Any, Callable[[Any], Any]]], refused: Any,
                 *, timeout: float) -> Any:
    """
    Show a modal prompt on the Qt main thread and wait for its answer.
    `build()` makes the dialog and returns (dialog, answer), where answer(code)
    reads the choice once it closes. `refused` is the answer when the wait
    expires; the dialog is then closed on the UI thread.
    """
    from aqt import mw
    from aqt.qt import Qt

    from ..shared.errors import AnkiBusyError
    from .ops import call_on_main

    cancelled = Event()
    active_dialog = None  # Read and written only on the UI thread.

    def close_expired_dialog() -> None:
        if active_dialog is not None:
            active_dialog.reject()

    def _ask() -> Any:
        nonlocal active_dialog
        # The UI callback may still be queued when the HTTP waiter expires.
        if cancelled.is_set():
            return refused
        dialog, answer = build()
        dialog.setWindowIcon(mw.windowIcon())
        # Added to the window's own flags, so a dialog keeps its title bar buttons.
        on_top = getattr(Qt, "WindowStaysOnTopHint", None) or Qt.WindowType.WindowStaysOnTopHint
        dialog.setWindowFlags(dialog.windowFlags() | on_top)
        if cancelled.is_set():
            return refused
        active_dialog = dialog
        try:
            code = dialog.exec()
        finally:
            active_dialog = None
        if cancelled.is_set():
            return refused
        return answer(code)

    try:
        return call_on_main(_ask, timeout=timeout)
    except AnkiBusyError:
        cancelled.set()
        # Qt's modal loop processes queued callbacks. Close on that thread;
        # never touch a widget from the HTTP worker or wait on it again here.
        mw.taskman.run_on_main(close_expired_dialog)
        return refused


def ask_permission_dialog(origin: Any, role: str = "Default", *, timeout: float = 120.0) -> PermissionDecision:
    """
    AnkiConnect's requestPermission: Allow / Don't allow. An allowed site calls
    without a key, so it gets the "No key, this computer" role, named here.
    """
    from aqt.qt import QCheckBox, QMessageBox

    def build() -> Tuple[Any, Callable[[Any], PermissionDecision]]:
        msg = QMessageBox(None)
        msg.setWindowTitle("Tsunagi")
        msg.setText(f'The website "{origin}" wants to use Anki through Tsunagi.')
        msg.setInformativeText(
            f'Without a key, it has the role of "No key, this computer": {role}. '
            "Allow only websites you trust."
        )
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        # Deny is the default: Enter or a stray click doesn't allow a website (6.26).
        msg.button(QMessageBox.StandardButton.Yes).setText("Allow")
        msg.button(QMessageBox.StandardButton.No).setText("Don't allow")
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.setCheckBox(QCheckBox(text="Don't ask again for this website", parent=msg))
        return msg, lambda pressed: PermissionDecision(
            accepted=pressed == QMessageBox.StandardButton.Yes,
            ignore=pressed == QMessageBox.StandardButton.No and msg.checkBox().isChecked(),
        )

    return _ask_on_main(build, PermissionDecision(), timeout=timeout)


# What the built-in roles let an app do, for the access prompt.
ROLE_BLURBS = {
    "default": "Read and change your collection, including deleting notes and decks, and open Anki's windows.",
    "read_only": "Read your collection; change nothing.",
    "everything": "Everything Tsunagi can do, including reading any file you can.",
}


def ask_access_dialog(request: Any, *, timeout: float = 120.0) -> Any:
    """
    POST /v1/permissions:request (6.124): who is asking, a role to give it,
    Allow / Don't allow (the default). `request` is an AccessAsk.
    """
    from aqt.qt import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, Qt, QVBoxLayout

    from .access_requests import AccessDecision

    def label(text: str) -> Any:
        """Rich text, always: the parts that come from the request are escaped."""
        widget = QLabel(text)
        widget.setTextFormat(Qt.TextFormat.RichText)
        widget.setWordWrap(True)
        return widget

    def build() -> Tuple[Any, Callable[[Any], Any]]:
        dialog = QDialog(None)
        dialog.setWindowTitle("Tsunagi")
        dialog.setMinimumWidth(480)  # wrapped labels would let it shrink to a narrow column
        font = dialog.font()
        font.setPointSizeF(font.pointSizeF() * 1.15)  # a step above Qt's small default
        dialog.setFont(font)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        again = request.existing is not None
        if request.origin:
            who = f'The website "{escape(request.origin)}"'
        else:
            where = f"a program on another device ({escape(request.address)})" if request.address \
                else "a program on this computer"
            who = f'"{escape(request.name)}", {where},'
        asks = "is asking for access again." if again else "wants to use Anki through Tsunagi."
        layout.addWidget(label(f'<span style="font-size: large; font-weight: 600">{who} {asks}</span>'))
        if not request.origin:
            layout.addWidget(label("A program names itself; Tsunagi can't check it."))
        if again:
            app, role, on = request.existing
            state = (f'It has access as "{escape(app)}", with the role {escape(role)}.' if on else
                     f'It has an app, "{escape(app)}" ({escape(role)}), which you turned off.')
            layout.addWidget(label(state))
        row = QHBoxLayout()
        row.addWidget(QLabel("Role:"))
        if again:
            # Before and after: the role it has, and the one it gets if you allow it.
            row.addWidget(label(f"<b>{escape(request.existing[1])}</b> &nbsp;&rarr;"))
        roles = QComboBox()
        for rid, name in request.roles:
            roles.addItem(name, rid)
        roles.setCurrentIndex(max(0, roles.findData(request.role)))
        row.addWidget(roles, 1)
        layout.addLayout(row)
        blurb = label("")
        layout.addWidget(blurb)

        def describe() -> None:
            blurb.setText(escape(ROLE_BLURBS.get(roles.currentData(),
                                                 "A role you made: Roles in Tsunagi's settings shows what it allows.")))
        roles.currentIndexChanged.connect(lambda _i: describe())
        describe()
        if again:
            back_on = "" if request.existing[2] else ", turns its app back on,"
            layout.addWidget(label(f"Allowing gives it a new key{back_on} and its old key stops working. "
                                   "Allow only what you trust."))
        else:
            layout.addWidget(label(f'It gets its own key, and appears in Apps &amp; keys as "{escape(request.name)}", '
                                   "where you can change or remove it. Allow only what you trust."))
        ignore = QCheckBox("Don't ask again for this " + ("website" if request.origin else "program"))
        layout.addWidget(ignore)
        buttons = QDialogButtonBox()
        allow = buttons.addButton("Allow", QDialogButtonBox.ButtonRole.AcceptRole)
        deny = buttons.addButton("Don't allow", QDialogButtonBox.ButtonRole.RejectRole)
        # Deny is the default: Enter or a stray click doesn't allow anything (6.26).
        allow.setAutoDefault(False)
        deny.setDefault(True)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        deny.setFocus()

        def answer(code: Any) -> Any:
            accepted = code == QDialog.DialogCode.Accepted
            return AccessDecision(accepted=accepted, role=roles.currentData(),
                                  ignore=not accepted and ignore.isChecked())
        return dialog, answer

    return _ask_on_main(build, AccessDecision(), timeout=timeout)


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
