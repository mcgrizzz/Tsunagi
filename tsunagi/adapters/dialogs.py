"""
Qt dialogs for the permission flow and the one-time AnkiConnect config import.
All aqt imports are function-local so this module stays importable headless.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ANKICONNECT_ID = "2055492159"

_IMPORT_TEXT = (
    "AnkiConnect is installed. Import its settings into Tsunagi?\n\n"
    "This copies the API key and the list of allowed website origins.\n\n"
    "The port is NOT imported - Tsunagi keeps its own port (7777) so both "
    "add-ons can run side by side."
)


@dataclass(frozen=True)
class PermissionDecision:
    accepted: bool = False
    ignore: bool = False

    def __bool__(self) -> bool:
        return self.accepted


def ask_permission_dialog(origin: Any) -> PermissionDecision:
    """
    Blocking Yes/No prompt on the Qt main thread.
    Returns the choice and whether a denied request should be ignored later.
    """
    from aqt import mw
    from aqt.qt import QCheckBox, QMessageBox, Qt

    from ..shared.errors import AnkiBusyError
    from .ops import call_on_main

    def _ask() -> PermissionDecision:
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
        pressed = msg.exec()
        return PermissionDecision(
            accepted=pressed == QMessageBox.StandardButton.Yes,
            ignore=pressed == QMessageBox.StandardButton.No and msg.checkBox().isChecked(),
        )

    try:
        return call_on_main(_ask, timeout=120.0)
    except AnkiBusyError:
        # Timed out waiting for the user. The dialog may still be open on the
        # main thread; a late "Yes" is discarded (the waiter is gone) - the
        # client already got "denied" and can simply retry.
        return PermissionDecision()


def offer_ankiconnect_import() -> None:
    """
    One-time offer to import AnkiConnect's config. Called on profile_did_open
    (main thread), after start_server.

    Flag semantics: ankiconnect_import_offered is set on accept AND decline,
    but NOT when AnkiConnect isn't installed - so users who install
    AnkiConnect later still get the offer.
    """
    from aqt import mw
    from aqt.qt import QMessageBox

    from .settings import settings

    if settings.get("ankiconnect_import_offered"):
        return
    ac = mw.addonManager.getConfig(ANKICONNECT_ID)
    if ac is None:
        return

    accepted = QMessageBox.question(mw, "Tsunagi", _IMPORT_TEXT) == QMessageBox.StandardButton.Yes

    changes: dict = {"ankiconnect_import_offered": True}
    if accepted:
        if ac.get("apiKey"):
            changes["api_key"] = ac["apiKey"]
        merged = list(settings.get("cors_allowlist", []))
        for origin in ac.get("webCorsOriginList") or []:
            if origin not in merged:
                merged.append(origin)
        changes["cors_allowlist"] = merged
    settings.update(**changes)
